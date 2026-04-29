#!/usr/bin/env python3
"""
Jeu de buzzer Arduino deux joueurs – Serveur Flask

Lancement : ./venv/bin/python app.py
"""

import glob
import json
import os
import queue
import random
import subprocess
import sys
import threading
import time

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

# ── Try to import pyserial ─────────────────────────────────────────────────
try:
    import serial
    import serial.tools.list_ports
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False

app = Flask(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
BAUD          = 9600
GO_DELAY_MIN  = 2.0   # s  (minimum random wait before signal)
GO_DELAY_MAX  = 5.0   # s  (maximum random wait before signal)
ROUND_TIMEOUT = 8.0   # s  (auto-DNF if player doesn't press)
REVEAL_DELAY  = 0.8   # s  (pause after last press before revealing result)
NEXT_ROUND_DELAY = 2.5  # s  (auto-advance delay in series modes)
RAPID_N           = 5
BEST_OF_N         = 3
SSE_QUEUE_SIZE    = 64   # max pending SSE frames per client before dropping
TIE_THRESHOLD_S   = 0.001  # s – presses closer than this are declared a tie

# ── Game modes ─────────────────────────────────────────────────────────────
MODES = {
    "reflex":     {"label": "Réflexe",       "desc": "Appuyez dès le signal"},
    "ghost":      {"label": "Fantôme",       "desc": "Chrono masqué"},
    "blackout":   {"label": "Blackout",      "desc": "Écran éteint au signal"},
    "rapid_fire": {"label": "Rafale",        "desc": f"Série de {RAPID_N} manches rapides"},
    "double_tap": {"label": "Double Frappe", "desc": "Appuyez deux fois de suite"},
    "best_of_3":  {"label": "Championnat",   "desc": f"Meilleur des {BEST_OF_N} manches"},
}

# ── SSE broadcaster ────────────────────────────────────────────────────────
_clients: list = []
_clients_lock = threading.Lock()


def _broadcast(event: str, data: dict) -> None:
    """Push an SSE frame to all connected clients."""
    msg = f"event:{event}\ndata:{json.dumps(data)}\n\n"
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def _sse_subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=SSE_QUEUE_SIZE)
    with _clients_lock:
        _clients.append(q)
    return q


def _sse_unsubscribe(q: queue.Queue) -> None:
    with _clients_lock:
        try:
            _clients.remove(q)
        except ValueError:
            pass


# ── Game State ─────────────────────────────────────────────────────────────
class GameState:
    """Thread-safe game state container."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.mode: str = "reflex"
        self.phase: str = "idle"   # idle | countdown | active | partial | finished
        self.cdown_ts: float | None = None   # server ts when countdown began
        self.go_ts: float | None = None      # server ts when signal fired
        self.go_delay: float | None = None   # random delay chosen this round
        # presses: player -> list of press timestamps
        self.presses: dict = {}
        self.result: dict | None = None      # computed result (revealed only at end)
        self.scores: dict = {"J1": 0, "J2": 0}
        self.round_num: int = 0
        self.total_rounds: int = 1
        self.series: list = []               # list of per-round result dicts
        self.sim: bool = False               # simulation mode (no Arduino)
        # scheduled timer handles
        self._go_timer: threading.Timer | None = None
        self._timeout_timer: threading.Timer | None = None
        self._reveal_timer: threading.Timer | None = None

    # ── snapshots ────────────────────────────────────────────────────────

    def public_snap(self) -> dict:
        """Snapshot safe to broadcast during active play (no timing spoilers)."""
        with self._lock:
            d: dict = {
                "mode": self.mode,
                "phase": self.phase,
                "scores": dict(self.scores),
                "round_num": self.round_num,
                "total_rounds": self.total_rounds,
                "sim": self.sim,
                "modes": MODES,
            }
            if self.cdown_ts is not None:
                d["cdown_ts"] = self.cdown_ts
                d["go_delay"] = self.go_delay
            if self.go_ts is not None:
                d["go_ts"] = self.go_ts
            # Which players have pressed (but NOT when) – needed for partial phase UI
            if self.phase in ("partial", "active"):
                d["pressed"] = list(self.presses.keys())
            # Reveal result only when finished
            if self.phase == "finished" and self.result is not None:
                d["result"] = self.result
            return d

    # ── internal helpers ──────────────────────────────────────────────────

    def _cancel_timers(self) -> None:
        for attr in ("_go_timer", "_timeout_timer", "_reveal_timer"):
            t = getattr(self, attr)
            if t is not None:
                t.cancel()
            setattr(self, attr, None)

    def _reset_round(self) -> None:
        self._cancel_timers()
        self.phase = "idle"
        self.cdown_ts = None
        self.go_ts = None
        self.go_delay = None
        self.presses = {}
        self.result = None

    def full_reset(self) -> None:
        with self._lock:
            self._reset_round()
            self.scores = {"J1": 0, "J2": 0}
            self.round_num = 0
            self.series = []
            self.total_rounds = 1


gs = GameState()


# ── LED / serial output ────────────────────────────────────────────────────
_serial_port = None
_serial_lock = threading.Lock()


def _send_serial(cmd: str) -> None:
    with _serial_lock:
        if _serial_port and _serial_port.is_open:
            try:
                _serial_port.write(cmd.encode())
            except Exception:
                pass


def _led_winner(winner: str | None) -> None:
    """Light the winner's LED (and turn off both first)."""
    _send_serial("ab")   # both LEDs off
    if winner == "J1":
        _send_serial("A")
    elif winner == "J2":
        _send_serial("B")
    # "tie" → both on
    elif winner == "tie":
        _send_serial("AB")


# ── Serial port detection & management ────────────────────────────────────
def _find_port() -> str | None:
    if not _SERIAL_AVAILABLE:
        return None
    # macOS usbmodem first, then Linux ACM/USB
    patterns = ["/dev/cu.usbmodem*", "/dev/tty.usbmodem*",
                 "/dev/ttyACM*", "/dev/ttyUSB*"]
    for pat in patterns:
        matches = glob.glob(pat)
        if matches:
            return matches[0]
    return None


def _kill_port_users(port: str) -> None:
    """Kill any process holding the serial port open.

    Note: uses ``lsof`` and ``kill``, which are Unix/Linux/macOS only.
    This function is a no-op on unsupported platforms.
    """
    if sys.platform == "win32":
        return
    try:
        out = subprocess.check_output(["lsof", "-t", port], text=True).strip()
        for pid in out.splitlines():
            try:
                subprocess.run(["kill", "-9", pid], check=False)
            except Exception:
                pass
    except Exception:
        pass


def _open_serial(port: str):
    if not _SERIAL_AVAILABLE:
        return None
    _kill_port_users(port)
    time.sleep(0.3)
    ser = serial.Serial(port, BAUD, timeout=0.1)
    return ser


def _serial_reader_thread() -> None:
    """Background thread: reads J1/J2 from Arduino and feeds the game engine."""
    global _serial_port
    while True:
        if _serial_port is None:
            port = _find_port()
            if port:
                try:
                    _serial_port = _open_serial(port)
                    gs.sim = False
                    _broadcast("state", gs.public_snap())
                    print(f"[serial] connecté sur {port}", flush=True)
                except Exception as e:
                    print(f"[serial] impossible d'ouvrir {port}: {e}", flush=True)
                    _serial_port = None
                    time.sleep(3)
                    continue
            else:
                if not gs.sim:
                    gs.sim = True
                    _broadcast("state", gs.public_snap())
                    print("[serial] mode simulation (pas d'Arduino détecté)", flush=True)
                time.sleep(3)
                continue

        try:
            raw = _serial_port.readline().decode(errors="ignore").strip()
            if raw in ("J1", "J2"):
                _on_player_press(raw)
        except Exception as e:
            print(f"[serial] erreur lecture: {e}", flush=True)
            _serial_port = None
            gs.sim = True
            time.sleep(1)


# ── Game engine ────────────────────────────────────────────────────────────

def _expected_presses() -> int:
    """How many presses per player are expected for the current mode."""
    return 2 if gs.mode == "double_tap" else 1


def _on_go() -> None:
    """Called when the signal fires (after random countdown delay)."""
    with gs._lock:
        if gs.phase != "countdown":
            return
        gs.phase = "active"
        gs.go_ts = time.time()
        gs._timeout_timer = threading.Timer(ROUND_TIMEOUT, _on_timeout)
        gs._timeout_timer.daemon = True
        gs._timeout_timer.start()
    _broadcast("state", gs.public_snap())


def _on_timeout() -> None:
    """Called when the round timer runs out without both players pressing."""
    with gs._lock:
        if gs.phase not in ("active", "partial"):
            return
        _compute_result_locked()


def _on_player_press(player: str) -> None:
    """Called whenever a player's button is pressed."""
    now = time.time()
    with gs._lock:
        if gs.phase not in ("active", "partial"):
            return

        presses = gs.presses.get(player, [])
        expected = _expected_presses()

        # In double_tap mode allow up to 2 presses per player
        if len(presses) >= expected:
            return  # already done

        presses.append(now)
        gs.presses[player] = presses

        # Check completion
        all_done = all(
            len(gs.presses.get(p, [])) >= expected
            for p in ("J1", "J2")
        )
        any_done = any(
            len(gs.presses.get(p, [])) >= expected
            for p in ("J1", "J2")
        )

        if all_done:
            gs._cancel_timers()
            gs._reveal_timer = threading.Timer(REVEAL_DELAY, _finalize_round)
            gs._reveal_timer.daemon = True
            gs._reveal_timer.start()
            # Phase stays "partial" until finalize (anti-cheat: don't reveal times yet)
            gs.phase = "partial"
        elif any_done:
            gs.phase = "partial"

    _broadcast("state", gs.public_snap())


def _compute_result_locked() -> None:
    """Compute the round result (must be called with gs._lock held)."""
    go = gs.go_ts
    expected = _expected_presses()

    def player_time(player: str) -> float | None:
        presses = gs.presses.get(player, [])
        if len(presses) < expected:
            return None
        return presses[-1] - go

    t1 = player_time("J1")
    t2 = player_time("J2")

    if t1 is None and t2 is None:
        winner = None
    elif t1 is None:
        winner = "J2"
    elif t2 is None:
        winner = "J1"
    elif abs(t1 - t2) < TIE_THRESHOLD_S:
        winner = "tie"
    else:
        winner = "J1" if t1 < t2 else "J2"

    # For double_tap mode, also expose both individual tap times
    tap_data = {}
    if gs.mode == "double_tap":
        for p in ("J1", "J2"):
            taps = gs.presses.get(p, [])
            tap_data[p] = [round((t - go) * 1000) for t in taps]

    gs.result = {
        "winner": winner,
        "t1_ms": round(t1 * 1000) if t1 is not None else None,
        "t2_ms": round(t2 * 1000) if t2 is not None else None,
        "taps": tap_data,
        "dnf": [p for p in ("J1", "J2") if player_time(p) is None],
    }
    gs.phase = "partial"   # will be set to "finished" in _finalize_round


def _finalize_round() -> None:
    """Transition to finished state, update scores, signal LEDs."""
    with gs._lock:
        if gs.phase not in ("partial", "active"):
            return
        _compute_result_locked()
        gs.phase = "finished"

        winner = gs.result["winner"] if gs.result else None
        if winner and winner != "tie":
            gs.scores[winner] = gs.scores.get(winner, 0) + 1

        # Record for series
        if gs.result:
            gs.series.append({**gs.result, "round": gs.round_num})

    _led_winner(winner)
    _broadcast("state", gs.public_snap())

    # Auto-advance in series modes
    mode = gs.mode
    if mode in ("rapid_fire", "best_of_3"):
        threading.Timer(NEXT_ROUND_DELAY, _auto_next_round).start()


def _auto_next_round() -> None:
    with gs._lock:
        if gs.phase != "finished":
            return
        done = _series_is_done_locked()
        if done:
            # Championship / rapid-fire over – stay finished
            return
        _start_round_locked()
    _broadcast("state", gs.public_snap())


def _series_is_done_locked() -> bool:
    mode = gs.mode
    if mode == "rapid_fire":
        return gs.round_num >= RAPID_N
    if mode == "best_of_3":
        threshold = (BEST_OF_N + 1) // 2
        return any(gs.scores[p] >= threshold for p in ("J1", "J2"))
    return True  # single-round modes always "done" after 1


def _start_round_locked() -> None:
    """Start a new round (must be called with gs._lock held)."""
    gs._reset_round()
    gs.round_num += 1
    gs.phase = "countdown"
    gs.cdown_ts = time.time()
    gs.go_delay = round(random.uniform(GO_DELAY_MIN, GO_DELAY_MAX), 3)
    gs._go_timer = threading.Timer(gs.go_delay, _on_go)
    gs._go_timer.daemon = True
    gs._go_timer.start()

    # Set series length for UI
    if gs.mode == "rapid_fire":
        gs.total_rounds = RAPID_N
    elif gs.mode == "best_of_3":
        gs.total_rounds = BEST_OF_N
    else:
        gs.total_rounds = 1


# ── Flask routes ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/modes")
def api_modes():
    return jsonify(MODES)


@app.route("/api/state")
def api_state():
    return jsonify(gs.public_snap())


@app.route("/api/start", methods=["POST"])
def api_start():
    body = request.get_json(silent=True) or {}
    mode = body.get("mode", gs.mode)
    if mode not in MODES:
        return jsonify({"error": "mode inconnu"}), 400

    with gs._lock:
        gs.full_reset()
        gs.mode = mode
        # For series modes, initialise total_rounds early so UI shows it
        if mode == "rapid_fire":
            gs.total_rounds = RAPID_N
        elif mode == "best_of_3":
            gs.total_rounds = BEST_OF_N
        _start_round_locked()

    _broadcast("state", gs.public_snap())
    return jsonify(gs.public_snap())


@app.route("/api/reset", methods=["POST"])
def api_reset():
    with gs._lock:
        gs.full_reset()
    _broadcast("state", gs.public_snap())
    return jsonify(gs.public_snap())


@app.route("/api/simulate_press", methods=["POST"])
def api_simulate_press():
    """Simulate a button press (used when Arduino is not connected)."""
    body = request.get_json(silent=True) or {}
    player = body.get("player")
    if player not in ("J1", "J2"):
        return jsonify({"error": "joueur invalide"}), 400
    _on_player_press(player)
    return jsonify({"ok": True})


@app.route("/api/set_mode", methods=["POST"])
def api_set_mode():
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    if mode not in MODES:
        return jsonify({"error": "mode inconnu"}), 400
    with gs._lock:
        if gs.phase != "idle" and gs.phase != "finished":
            return jsonify({"error": "round en cours"}), 409
        gs.mode = mode
    _broadcast("state", gs.public_snap())
    return jsonify(gs.public_snap())


@app.route("/events")
def sse_stream():
    """Server-Sent Events endpoint – pushes state changes in real time."""
    q = _sse_subscribe()

    def generate():
        # Send initial state immediately
        yield f"event:state\ndata:{json.dumps(gs.public_snap())}\n\n"
        try:
            while True:
                try:
                    msg = q.get(timeout=20)
                    yield msg
                except queue.Empty:
                    # Keep-alive comment
                    yield ": ka\n\n"
        except GeneratorExit:
            pass
        finally:
            _sse_unsubscribe(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    t = threading.Thread(target=_serial_reader_thread, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"[app] démarrage sur http://0.0.0.0:{port}", flush=True)
    # use_reloader=False to avoid spawning two serial threads
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
