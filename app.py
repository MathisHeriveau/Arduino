import copy
import glob
import json
import os
import queue
import random
import signal
import subprocess
import threading
import time

import serial
from flask import Flask, Response, jsonify, render_template, request
from serial.tools import list_ports

PREFERRED_PORT = os.environ.get("ARDUINO_PORT", "/dev/cu.usbmodem101")
BAUDRATE = int(os.environ.get("ARDUINO_BAUDRATE", "9600"))
PLAYERS = ("J1", "J2")

MODES = {
    "ghost": {
        "key": "ghost",
        "name": "Timer Fantome",
        "kind": "precision",
        "description": "Un chrono visible quelques instants, puis plus rien. Le plus proche de la cible gagne.",
        "hero": "Precision pure, score masque jusqu'a la revelation.",
        "theme": "ember",
        "target_min": 6,
        "target_max": 15,
        "hide_after": 2.4,
        "rounds_to_win": 1,
        "reveal_delay": 1.1,
    },
    "blackout": {
        "key": "blackout",
        "name": "Blackout",
        "kind": "precision",
        "description": "La cible apparait, le chrono s'efface presque tout de suite, et l'ecran plonge dans le noir.",
        "hero": "Mode gala. Rien a lire, tout a ressentir.",
        "theme": "void",
        "target_min": 5,
        "target_max": 12,
        "hide_after": 0.9,
        "rounds_to_win": 1,
        "reveal_delay": 1.3,
        "blackout": True,
    },
    "doubletap": {
        "key": "doubletap",
        "name": "Double Impact",
        "kind": "doubletap",
        "description": "Chaque joueur doit faire deux appuis. L'intervalle entre ses deux buzz doit coller a la cible.",
        "hero": "Deux impulsions, un seul bon rythme.",
        "theme": "cyan",
        "target_min": 2,
        "target_max": 7,
        "hide_after": 0.8,
        "rounds_to_win": 1,
        "reveal_delay": 1.1,
    },
    "royale": {
        "key": "royale",
        "name": "Serie Royale",
        "kind": "precision",
        "description": "Un best of three de precision. Rien n'est montre avant la fin de chaque manche.",
        "hero": "Premier a trois points. Ambiance finale assuree.",
        "theme": "gold",
        "target_min": 4,
        "target_max": 11,
        "hide_after": 1.6,
        "rounds_to_win": 3,
        "reveal_delay": 1.0,
    },
    "reflex": {
        "key": "reflex",
        "name": "Reflex Noir",
        "kind": "reflex",
        "description": "Attendez GO. Le premier appui apres le signal gagne. Faux depart sanctionne.",
        "hero": "Ne bougez pas trop tot.",
        "theme": "pulse",
        "go_delay_min": 2.2,
        "go_delay_max": 5.2,
        "rounds_to_win": 1,
        "reveal_delay": 0.9,
    },
    "rapidfire": {
        "key": "rapidfire",
        "name": "Rapid Fire",
        "kind": "reflex",
        "description": "Une serie reflexe ultra nerveuse. Premier a trois points.",
        "hero": "Trois points pour survivre au rythme.",
        "theme": "storm",
        "go_delay_min": 1.4,
        "go_delay_max": 3.0,
        "rounds_to_win": 3,
        "reveal_delay": 0.75,
    },
}


def new_player_state():
    return {
        "presses": [],
        "finished": False,
        "result": None,
        "difference": None,
        "status": "Pret",
    }


def other_player(player):
    return "J2" if player == "J1" else "J1"


def format_seconds(value):
    if value is None:
        return "--"
    return f"{value:.3f} s"


class StateStream:
    def __init__(self):
        self.listeners = []
        self.lock = threading.Lock()

    def subscribe(self):
        listener = queue.Queue(maxsize=1)
        with self.lock:
            self.listeners.append(listener)
        return listener

    def unsubscribe(self, listener):
        with self.lock:
            if listener in self.listeners:
                self.listeners.remove(listener)

    def publish(self, payload):
        encoded = json.dumps(payload)
        with self.lock:
            listeners = list(self.listeners)

        for listener in listeners:
            try:
                if listener.full():
                    listener.get_nowait()
            except queue.Empty:
                pass

            try:
                listener.put_nowait(encoded)
            except queue.Full:
                pass


class SerialBridge:
    def __init__(self, preferred_port, baudrate):
        self.preferred_port = preferred_port
        self.baudrate = baudrate
        self.device = None
        self.serial = None
        self.lock = threading.Lock()
        self.connected = False
        self.connection_error = None
        self.killed_pids = []

    def discover_ports(self):
        candidates = []

        if self.preferred_port:
            candidates.append(self.preferred_port)

        for port in list_ports.comports():
            if "usbmodem" in port.device:
                candidates.append(port.device)

        for pattern in ("/dev/cu.usbmodem*", "/dev/tty.usbmodem*"):
            candidates.extend(glob.glob(pattern))

        seen = set()
        unique_candidates = []
        for candidate in candidates:
            if candidate and candidate not in seen:
                unique_candidates.append(candidate)
                seen.add(candidate)
        return unique_candidates

    def terminate_blocking_processes(self, devices):
        existing_devices = [device for device in devices if os.path.exists(device)]
        if not existing_devices:
            return []

        try:
            result = subprocess.run(
                ["lsof", "-t", *existing_devices],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            print("lsof introuvable, nettoyage auto ignore.")
            return []

        pids = []
        for raw_pid in result.stdout.splitlines():
            raw_pid = raw_pid.strip()
            if not raw_pid:
                continue
            try:
                pid = int(raw_pid)
            except ValueError:
                continue
            if pid == os.getpid() or pid in pids:
                continue
            pids.append(pid)

        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except PermissionError:
                print(f"Impossible d'arreter le PID {pid}.")

        time.sleep(0.35)

        for pid in pids:
            try:
                os.kill(pid, 0)
            except OSError:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

        return pids

    def connect(self):
        devices = self.discover_ports()
        self.killed_pids = self.terminate_blocking_processes(devices)

        if self.killed_pids:
            print(f"Processus bloques sur usbmodem termines : {self.killed_pids}")

        last_error = None
        for device in devices:
            if not os.path.exists(device):
                continue
            try:
                print(f"Tentative de connexion a {device}...")
                self.serial = serial.Serial(device, self.baudrate, timeout=0.02)
                time.sleep(2)
                self.device = device
                self.connected = True
                self.connection_error = None
                print(f"Arduino connecte sur {device} ✅")
                self.show_ready()
                return
            except Exception as exc:
                last_error = str(exc)

        self.connected = False
        self.device = None
        if last_error:
            self.connection_error = last_error
            print(f"Connexion serie indisponible: {last_error}")
        else:
            self.connection_error = "Aucun port usbmodem detecte."
            print("Aucun Arduino usbmodem detecte, mode clavier disponible.")

    def send(self, cmd):
        if not self.connected or self.serial is None:
            return False
        with self.lock:
            try:
                self.serial.write(cmd.encode())
                return True
            except Exception as exc:
                self.connected = False
                self.connection_error = str(exc)
                print(f"Erreur d'envoi serie: {exc}")
                return False

    def clear(self):
        self.send("a")
        self.send("b")

    def show_ready(self):
        self.send("A")
        self.send("B")

    def blink_winner(self, winner, duration=7):
        if not self.connected:
            return

        led_on = "A" if winner == "J1" else "B"
        led_off = "a" if winner == "J1" else "b"

        end = time.time() + duration
        self.clear()

        while time.time() < end and self.connected:
            self.send(led_on)
            time.sleep(0.18)
            self.send(led_off)
            time.sleep(0.18)

        self.send(led_on)

    def start_reader(self, callback):
        if not self.connected or self.serial is None:
            return

        def read_loop():
            print("Lecture des buzzers activee.")
            while True:
                try:
                    raw = self.serial.readline()
                    if not raw:
                        time.sleep(0.005)
                        continue

                    line = raw.decode(errors="ignore").strip()
                    if line in PLAYERS:
                        callback(line)
                except Exception as exc:
                    self.connected = False
                    self.connection_error = str(exc)
                    print(f"Lecture serie interrompue: {exc}")
                    break

        threading.Thread(target=read_loop, daemon=True).start()

    def snapshot(self):
        return {
            "connected": self.connected,
            "error": self.connection_error,
        }


class GameEngine:
    def __init__(self, bridge, on_state_change=None):
        self.bridge = bridge
        self.on_state_change = on_state_change
        self.lock = threading.Lock()
        self.events = []
        self.mode_key = "ghost"
        self.phase = "idle"
        self.message = "Choisissez un mode puis lancez la scene."
        self.round_number = 0
        self.round_started_at = None
        self.round_finished_at = None
        self.go_at = None
        self.reveal_at = None
        self.target = None
        self.score = {player: 0 for player in PLAYERS}
        self.players = {player: new_player_state() for player in PLAYERS}
        self.winner = None
        self.pending_winner = None
        self.pending_message = None
        self.match_winner = None
        self._log("Salon de jeu initialise.")
        self._apply_mode("ghost")

    def _log(self, message):
        self.events.insert(0, message)
        self.events = self.events[:10]
        print(message)

    def _mode(self):
        return MODES[self.mode_key]

    def _reset_players(self):
        self.players = {player: new_player_state() for player in PLAYERS}

    def _reset_round(self):
        self.round_started_at = None
        self.round_finished_at = None
        self.go_at = None
        self.reveal_at = None
        self.target = None
        self.winner = None
        self.pending_winner = None
        self.pending_message = None
        self._reset_players()

    def _apply_mode(self, mode_key):
        self.mode_key = mode_key
        self.phase = "idle"
        self.message = MODES[mode_key]["hero"]
        self.round_number = 0
        self.match_winner = None
        self.score = {player: 0 for player in PLAYERS}
        self._reset_round()
        self.bridge.show_ready()
        self._log(f"Mode actif: {MODES[mode_key]['name']}.")

    def _emit_state_change_locked(self):
        if self.on_state_change is not None:
            self.on_state_change(self._snapshot_unlocked())

    def select_mode(self, mode_key):
        if mode_key not in MODES:
            raise ValueError("Mode inconnu.")
        with self.lock:
            if self.phase in {"arming", "live", "awaiting_reveal"}:
                raise ValueError("Impossible de changer de mode pendant une manche.")
            self._apply_mode(mode_key)
            self._emit_state_change_locked()

    def reset_mode(self):
        with self.lock:
            self._apply_mode(self.mode_key)
            self._log("Mode reinitialise.")
            self._emit_state_change_locked()

    def advance(self):
        with self.lock:
            self._tick_locked(time.time())
            if self.phase in {"arming", "live", "awaiting_reveal"}:
                return False, "Une manche est deja en cours."

            if self.phase != "between_rounds":
                self.score = {player: 0 for player in PLAYERS}
                self.match_winner = None
                self.round_number = 0

            self.round_number += 1
            self._reset_round()

            now = time.time()
            mode = self._mode()
            if mode["kind"] in {"precision", "doubletap"}:
                self.round_started_at = now
                self.target = random.randint(mode["target_min"], mode["target_max"])
                self.phase = "live"
                if mode["kind"] == "doubletap":
                    self.message = (
                        f"Cible {self.target} secondes. Deux buzz par joueur."
                    )
                    self._log(
                        f"Manche {self.round_number}: cible {self.target}s en Double Impact."
                    )
                else:
                    self.message = f"Cible {self.target} secondes. Top chrono."
                    self._log(
                        f"Manche {self.round_number}: cible {self.target}s dans {mode['name']}."
                    )
                self.bridge.show_ready()
                self._emit_state_change_locked()
                return True, "Manche lancee."

            delay = round(
                random.uniform(mode["go_delay_min"], mode["go_delay_max"]),
                2,
            )
            self.phase = "arming"
            self.go_at = now + delay
            self.message = "Attendez le signal. Aucun faux depart."
            self.bridge.clear()
            self._log(
                f"Manche {self.round_number}: {mode['name']} arme, GO dans {delay}s."
            )
            self._emit_state_change_locked()
            return True, "Manche lancee."

    def simulate_press(self, player):
        if player not in PLAYERS:
            raise ValueError("Joueur inconnu.")
        self.register_press(player)

    def register_press(self, player):
        with self.lock:
            now = time.time()
            self._tick_locked(now)

            if self.phase not in {"arming", "live"}:
                return

            mode_kind = self._mode()["kind"]
            if mode_kind == "precision":
                self._handle_precision_press(player, now)
                self._emit_state_change_locked()
                return

            if mode_kind == "doubletap":
                self._handle_doubletap_press(player, now)
                self._emit_state_change_locked()
                return

            self._handle_reflex_press(player, now)
            self._emit_state_change_locked()

    def _handle_precision_press(self, player, now):
        player_state = self.players[player]
        if player_state["finished"] or self.round_started_at is None:
            return

        elapsed = now - self.round_started_at
        player_state["presses"] = [now]
        player_state["finished"] = True
        player_state["result"] = round(elapsed, 3)
        player_state["difference"] = round(abs(elapsed - self.target), 3)
        player_state["status"] = "Verrouille"
        finished_count = sum(
            1 for current_player in PLAYERS if self.players[current_player]["finished"]
        )

        if finished_count < len(PLAYERS):
            self.message = f"{finished_count}/2 joueurs verrouilles."
            return

        diff1 = self.players["J1"]["difference"]
        diff2 = self.players["J2"]["difference"]

        if diff1 < diff2:
            self.players["J1"]["status"] = "Le plus proche"
            self.players["J2"]["status"] = "Peut mieux faire"
            self._queue_reveal(
                now,
                "J1",
                f"J1 gagne avec {diff1:.3f}s d'ecart.",
            )
            return

        if diff2 < diff1:
            self.players["J2"]["status"] = "Le plus proche"
            self.players["J1"]["status"] = "Peut mieux faire"
            self._queue_reveal(
                now,
                "J2",
                f"J2 gagne avec {diff2:.3f}s d'ecart.",
            )
            return

        self.players["J1"]["status"] = "Egalite parfaite"
        self.players["J2"]["status"] = "Egalite parfaite"
        self._queue_reveal(
            now,
            "egalite",
            f"Egalite parfaite a {diff1:.3f}s d'ecart.",
        )

    def _handle_doubletap_press(self, player, now):
        player_state = self.players[player]
        if player_state["finished"]:
            return

        if not player_state["presses"]:
            player_state["presses"].append(now)
            player_state["status"] = "Premiere impulsion"
            self.message = "Enregistrez la seconde impulsion."
            return

        interval = now - player_state["presses"][0]
        player_state["presses"].append(now)
        player_state["finished"] = True
        player_state["result"] = round(interval, 3)
        player_state["difference"] = round(abs(interval - self.target), 3)
        player_state["status"] = "Double impact verrouille"
        finished_count = sum(
            1 for current_player in PLAYERS if self.players[current_player]["finished"]
        )

        if finished_count < len(PLAYERS):
            self.message = f"{finished_count}/2 joueurs verrouilles."
            return

        diff1 = self.players["J1"]["difference"]
        diff2 = self.players["J2"]["difference"]

        if diff1 < diff2:
            self.players["J1"]["status"] = "Rythme parfait"
            self.players["J2"]["status"] = "Trop large"
            self._queue_reveal(
                now,
                "J1",
                f"J1 gagne l'intervalle avec {diff1:.3f}s d'ecart.",
            )
            return

        if diff2 < diff1:
            self.players["J2"]["status"] = "Rythme parfait"
            self.players["J1"]["status"] = "Trop large"
            self._queue_reveal(
                now,
                "J2",
                f"J2 gagne l'intervalle avec {diff2:.3f}s d'ecart.",
            )
            return

        self.players["J1"]["status"] = "Meme rythme"
        self.players["J2"]["status"] = "Meme rythme"
        self._queue_reveal(
            now,
            "egalite",
            f"Egalite parfaite sur l'intervalle a {diff1:.3f}s.",
        )

    def _handle_reflex_press(self, player, now):
        mode = self._mode()
        player_state = self.players[player]
        if player_state["finished"]:
            return

        if self.phase == "arming":
            offender = player
            winner = other_player(player)
            self.players[offender]["status"] = "Faux depart"
            self.players[winner]["status"] = "Victoire sur faute"
            self._queue_reveal(
                now,
                winner,
                f"{offender} part trop tot. Point pour {winner}.",
            )
            return

        if self.round_started_at is None:
            return

        reaction = now - self.round_started_at
        player_state["presses"] = [now]
        player_state["finished"] = True
        player_state["result"] = round(reaction, 3)
        player_state["status"] = "Le plus vif"
        loser = other_player(player)
        self.players[loser]["status"] = "Trop tard"
        self._queue_reveal(
            now,
            player,
            f"{player} gagne en {reaction:.3f}s dans {mode['name']}.",
        )

    def _queue_reveal(self, now, winner, public_message):
        self.phase = "awaiting_reveal"
        self.round_finished_at = now
        self.reveal_at = now + self._mode()["reveal_delay"]
        self.pending_winner = winner
        self.pending_message = public_message
        self.message = "Impacts enregistres. Revelation imminente."

    def _finalize_reveal(self):
        winner = self.pending_winner
        self.winner = winner
        self.pending_winner = None
        self.phase = "round_over"
        self.message = self.pending_message or self.message
        self.pending_message = None

        if winner in PLAYERS:
            self.score[winner] += 1
            threading.Thread(
                target=self.bridge.blink_winner,
                args=(winner,),
                daemon=True,
            ).start()
        else:
            self.bridge.show_ready()

        rounds_to_win = self._mode()["rounds_to_win"]
        if rounds_to_win > 1:
            if winner in PLAYERS and self.score[winner] >= rounds_to_win:
                self.phase = "match_over"
                self.match_winner = winner
                self.message = (
                    f"{winner} remporte {self._mode()['name']} "
                    f"{self.score[winner]} a {self.score[other_player(winner)]}."
                )
            else:
                self.phase = "between_rounds"
                if winner == "egalite":
                    self.message = "Egalite. Manche suivante disponible."
                else:
                    self.message = (
                        f"Score {self.score['J1']} - {self.score['J2']}. "
                        "Manche suivante prete."
                    )

    def _tick_locked(self, now):
        changed = False

        if self.phase == "arming" and self.go_at is not None and now >= self.go_at:
            self.phase = "live"
            self.round_started_at = now
            self.go_at = None
            self.message = "GO"
            self.bridge.show_ready()
            changed = True

        if (
            self.phase == "awaiting_reveal"
            and self.reveal_at is not None
            and now >= self.reveal_at
        ):
            self._finalize_reveal()
            changed = True

        return changed

    def _results_visible(self):
        return self.phase in {"idle", "round_over", "between_rounds", "match_over"}

    def _player_view(self, player_key):
        player = self.players[player_key]
        mode_kind = self._mode()["kind"]
        results_visible = self._results_visible()

        if mode_kind == "precision":
            metric_label = "Chrono"
            detail_label = "Ecart"
            if results_visible and player["result"] is not None:
                metric_value = format_seconds(player["result"])
                detail_value = format_seconds(player["difference"])
            elif player["finished"]:
                metric_value = "LOCK"
                detail_value = "Secret"
            else:
                metric_value = "--"
                detail_value = "--"
            status = player["status"] if results_visible else (
                "Verrouille" if player["finished"] else "En jeu"
            )
        elif mode_kind == "doubletap":
            metric_label = "Intervalle"
            detail_label = "Ecart"
            if results_visible and player["result"] is not None:
                metric_value = format_seconds(player["result"])
                detail_value = format_seconds(player["difference"])
            elif player["finished"]:
                metric_value = "LOCK"
                detail_value = "Secret"
            elif len(player["presses"]) == 1:
                metric_value = "1 / 2"
                detail_value = "Arme"
            else:
                metric_value = "--"
                detail_value = "--"
            if results_visible:
                status = player["status"]
            elif player["finished"]:
                status = "Verrouille"
            elif len(player["presses"]) == 1:
                status = "Premiere impulsion"
            else:
                status = "En jeu"
        else:
            metric_label = "Reaction"
            detail_label = "Statut"
            if results_visible and player["result"] is not None:
                metric_value = format_seconds(player["result"])
            elif self.phase == "awaiting_reveal":
                metric_value = "LOCK"
            elif player["finished"]:
                metric_value = "LOCK"
            else:
                metric_value = "--"
            detail_value = player["status"] if results_visible else (
                "Signal capture" if self.phase == "awaiting_reveal" else "Stand by"
            )
            status = player["status"] if results_visible else (
                "Signal capture" if self.phase == "awaiting_reveal" else "Pret"
            )

        return {
            "name": player_key,
            "metricLabel": metric_label,
            "metricValue": metric_value,
            "detailLabel": detail_label,
            "detailValue": detail_value,
            "status": status,
            "winner": self.winner == player_key or self.match_winner == player_key,
            "locked": player["finished"],
        }

    def _display_payload(self, now):
        mode = self._mode()
        kind = mode["kind"]

        payload = {
            "value": "--",
            "hint": mode["hero"],
            "style": "idle",
            "targetText": "Pret a lancer la scene",
            "dynamicTimer": False,
            "blackout": bool(mode.get("blackout")),
        }

        if kind == "precision":
            payload["targetText"] = (
                f"Cible {self.target} secondes"
                if self.target is not None
                else "Cible en attente"
            )
            if self.phase == "live" and self.round_started_at is not None:
                payload["dynamicTimer"] = True
                payload["hint"] = "Gardez le tempo."
                payload["style"] = "live"
            elif self.phase == "awaiting_reveal":
                payload["value"] = "LOCK"
                payload["hint"] = "Les deux temps sont captures."
                payload["style"] = "locked"
                payload["targetText"] = "Revelation en cours"
            elif self._results_visible() and self.winner == "egalite":
                payload["value"] = "EGA"
                payload["hint"] = self.message
                payload["style"] = "reveal"
                payload["targetText"] = (
                    f"Cible {self.target} secondes"
                    if self.target is not None
                    else "Cible revelee"
                )
            elif self._results_visible() and self.winner in PLAYERS:
                payload["value"] = self.winner
                payload["hint"] = self.message
                payload["style"] = "reveal"
                payload["targetText"] = f"Cible {self.target} secondes"
            return payload

        if kind == "doubletap":
            payload["targetText"] = (
                f"Intervalle cible {self.target} secondes"
                if self.target is not None
                else "Intervalle en attente"
            )
            if self.phase == "live":
                payload["dynamicTimer"] = True
                payload["hint"] = "Chaque joueur doit buzzer deux fois."
                payload["style"] = "live"
            elif self.phase == "awaiting_reveal":
                payload["value"] = "LOCK"
                payload["hint"] = "Les deux intervalles sont captures."
                payload["style"] = "locked"
                payload["targetText"] = "Revelation en cours"
            elif self._results_visible() and self.winner == "egalite":
                payload["value"] = "EGA"
                payload["hint"] = self.message
                payload["style"] = "reveal"
            elif self._results_visible() and self.winner in PLAYERS:
                payload["value"] = self.winner
                payload["hint"] = self.message
                payload["style"] = "reveal"
            return payload

        payload["targetText"] = "Attendez le signal"
        if self.phase == "arming":
            payload["value"] = "..."
            payload["hint"] = "Ne touchez a rien."
            payload["style"] = "warning"
        elif self.phase == "live":
            payload["value"] = "GO"
            payload["hint"] = "Premier impact gagnant."
            payload["style"] = "go"
            payload["targetText"] = "Feu vert"
        elif self.phase == "awaiting_reveal":
            payload["value"] = "LOCK"
            payload["hint"] = "Signal capture."
            payload["style"] = "locked"
            payload["targetText"] = "Revelation en cours"
        elif self._results_visible() and self.winner == "egalite":
            payload["value"] = "EGA"
            payload["hint"] = self.message
            payload["style"] = "reveal"
        elif self._results_visible() and self.winner in PLAYERS:
            payload["value"] = self.winner
            payload["hint"] = self.message
            payload["style"] = "reveal"
        return payload

    def _snapshot_unlocked(self):
        now = time.time()
        mode = self._mode()
        show_score = self.phase in {
            "idle",
            "round_over",
            "between_rounds",
            "match_over",
        }

        scoreboard = {
            "visible": show_score,
            "j1": self.score["J1"],
            "j2": self.score["J2"],
            "headline": (
                "Score masque pendant la manche"
                if not show_score
                else f"J1 {self.score['J1']}  |  J2 {self.score['J2']}"
            ),
            "subline": (
                "Manche seche"
                if mode["rounds_to_win"] == 1
                else f"Premier a {mode['rounds_to_win']}"
            ),
        }

        controls = {
            "canAdvance": self.phase not in {"arming", "live", "awaiting_reveal"},
            "advanceLabel": {
                "idle": "Entrer en scene",
                "round_over": "Nouvelle manche",
                "between_rounds": "Manche suivante",
                "match_over": "Nouvelle serie",
            }.get(self.phase, "En cours"),
        }

        phase_labels = {
            "idle": "Pret",
            "arming": "Sous tension",
            "live": "Live",
            "awaiting_reveal": "Revelation",
            "round_over": "Resultat",
            "between_rounds": "Intermanche",
            "match_over": "Finale",
        }

        return {
            "connection": self.bridge.snapshot(),
            "mode": self.mode_key,
            "modeInfo": copy.deepcopy(mode),
            "modes": copy.deepcopy(list(MODES.values())),
            "phase": self.phase,
            "phaseLabel": phase_labels[self.phase],
            "message": self.message,
            "round": self.round_number,
            "winner": self.winner,
            "matchWinner": self.match_winner,
            "players": {
                player_key: self._player_view(player_key) for player_key in PLAYERS
            },
            "scoreboard": scoreboard,
            "display": self._display_payload(now),
            "controls": controls,
            "timing": {
                "serverTime": now,
                "roundStartedAt": self.round_started_at,
                "roundFinishedAt": self.round_finished_at,
                "goAt": self.go_at,
                "revealAt": self.reveal_at,
                "hideAfter": mode.get("hide_after"),
                "kind": mode["kind"],
                "blackout": bool(mode.get("blackout")),
            },
        }

    def snapshot(self):
        with self.lock:
            self._tick_locked(time.time())
            return self._snapshot_unlocked()

    def tick(self):
        with self.lock:
            changed = self._tick_locked(time.time())
            if not changed:
                return None
            snapshot = self._snapshot_unlocked()

        if self.on_state_change is not None:
            self.on_state_change(snapshot)
        return snapshot


print("Demarrage du serveur...")

stream = StateStream()
bridge = SerialBridge(PREFERRED_PORT, BAUDRATE)
bridge.connect()

engine = GameEngine(bridge, on_state_change=stream.publish)
bridge.start_reader(engine.register_press)

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify(engine.snapshot())


@app.route("/api/stream")
def api_stream():
    listener = stream.subscribe()

    def event_stream():
        try:
            yield f"data: {json.dumps(engine.snapshot())}\n\n"
            while True:
                try:
                    payload = listener.get(timeout=15)
                    yield f"data: {payload}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            stream.unsubscribe(listener)

    response = Response(event_stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.route("/api/game", methods=["POST"])
def api_game():
    payload = request.get_json(silent=True) or {}
    action = payload.get("action")

    try:
        if action == "select_mode":
            engine.select_mode(payload.get("mode", ""))
        elif action == "advance":
            engine.advance()
        elif action == "reset":
            engine.reset_mode()
        elif action == "simulate_press":
            engine.simulate_press(payload.get("player", ""))
        else:
            return jsonify({"ok": False, "error": "Action inconnue."}), 400
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True, "state": engine.snapshot()})


def background_clock():
    while True:
        engine.tick()
        time.sleep(0.02)


threading.Thread(target=background_clock, daemon=True).start()

print("Serveur lance sur http://127.0.0.1:5000")
app.run(debug=False, threaded=True)
