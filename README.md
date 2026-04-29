# Jeu de Buzzer Arduino

Jeu de réflexe deux joueurs pour événements / galas.  
L'arbitre démarre les manches depuis un navigateur ; les joueurs appuient sur leurs buzzers physiques (Arduino) ou sur des touches clavier en mode simulation.

---

## Table des matières

1. [Aperçu](#aperçu)
2. [Architecture](#architecture)
3. [Câblage Arduino](#câblage-arduino)
4. [Flash du firmware](#flash-du-firmware)
5. [Installation Python](#installation-python)
6. [Lancement local](#lancement-local)
7. [Modes de jeu](#modes-de-jeu)
8. [Contrôles clavier (simulation)](#contrôles-clavier-simulation)
9. [Protocole série](#protocole-série)

---

## Aperçu

| Composant | Technologie |
|-----------|-------------|
| Backend   | Python 3.10+ (testé sur 3.12) + Flask |
| Frontend  | HTML/CSS/JS vanilla (SSE temps réel) |
| Firmware  | Arduino C++ (`.ino` / `arduino.cpp`) |

- Pas de polling : mises à jour en temps réel via **Server-Sent Events**.
- Le chrono est animé **côté client** à partir du timestamp `go_ts` envoyé par le serveur.
- **Anti-triche** : les temps ne sont révélés qu'après la fin de la manche.
- Détection automatique du port série (`/dev/cu.usbmodem*`, `/dev/ttyACM*`, etc.)
- **Mode simulation** automatique si aucun Arduino n'est connecté.

---

## Architecture

```
app.py                 ← serveur Flask
│  /                   ← UI plein écran
│  /events             ← flux SSE (mises à jour en temps réel)
│  /api/start          ← démarrer une partie
│  /api/reset          ← réinitialiser
│  /api/set_mode       ← changer de mode
│  /api/simulate_press ← simuler un appui (mode sans Arduino)
│
├─ templates/index.html
├─ static/style.css
├─ static/app.js
└─ arduino.cpp         ← firmware Arduino
```

---

## Câblage Arduino

| Composant       | Broche Arduino |
|-----------------|---------------|
| Bouton Joueur 1 | 2 (INPUT_PULLUP, actif bas) |
| Bouton Joueur 2 | 3 (INPUT_PULLUP, actif bas) |
| LED Joueur 1    | 8 (via résistance 220 Ω vers GND) |
| LED Joueur 2    | 9 (via résistance 220 Ω vers GND) |

---

## Flash du firmware

1. Renommer `arduino.cpp` en `arduino.ino` (ou créer un sketch `arduino/arduino.ino`).
2. Ouvrir dans l'**IDE Arduino** (≥ 2.x).
3. Sélectionner la carte (`Arduino Uno` / `Nano` / etc.) et le port COM.
4. Cliquer **Téléverser**.

Ou avec `arduino-cli` :

```bash
arduino-cli compile --fqbn arduino:avr:uno arduino.cpp
arduino-cli upload  --fqbn arduino:avr:uno --port /dev/cu.usbmodem* arduino.cpp
```

---

## Installation Python

```bash
# Créer le virtualenv
python3 -m venv venv

# Activer (macOS/Linux)
source venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

---

## Lancement local

```bash
# Option 1 – script fourni
chmod +x start.sh
./start.sh

# Option 2 – make
make run

# Option 3 – directement
./venv/bin/python app.py
```

Ouvrir <http://localhost:5000> dans un navigateur.

---

## Modes de jeu

| Mode | Description |
|------|-------------|
| **Réflexe** | Chrono visible, signal vert → appuyez le plus vite |
| **Fantôme** | Chrono masqué pendant la manche |
| **Blackout** | L'écran s'éteint au signal (orientation spatiale) |
| **Rafale** | Série de 5 manches rapides, cumul des points |
| **Double Frappe** | Chaque joueur appuie **deux fois** ; temps total mesuré |
| **Championnat** | Meilleur des 3, arrêt dès qu'un joueur atteint 2 victoires |

---

## Contrôles clavier (simulation)

Quand aucun Arduino n'est connecté, le serveur passe automatiquement en **mode simulation**.

| Touche | Action |
|--------|--------|
| `Q` ou `Espace` | Appui Joueur 1 |
| `P` ou `Entrée` | Appui Joueur 2 |

---

## Protocole série

Vitesse : **9600 baud**

| Direction | Message | Signification |
|-----------|---------|---------------|
| Arduino → PC | `J1\n` | Joueur 1 a appuyé |
| Arduino → PC | `J2\n` | Joueur 2 a appuyé |
| PC → Arduino | `A`    | Allume LED Joueur 1 |
| PC → Arduino | `a`    | Éteint LED Joueur 1 |
| PC → Arduino | `B`    | Allume LED Joueur 2 |
| PC → Arduino | `b`    | Éteint LED Joueur 2 |