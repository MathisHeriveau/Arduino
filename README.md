# Arduino Buzzer Game

Jeu de buzzer a 2 joueurs avec Arduino + interface web Flask en plein ecran.

Le projet est pense pour une ambiance "gala" ou "scene":
- interface sombre et immersive
- plusieurs modes de jeu
- masquage anti-triche des resultats pendant la manche
- retour LED sur les buzzers
- fallback clavier si l'Arduino n'est pas branche

## Apercu

Le systeme est compose de 2 parties:

1. `arduino.cpp`
   Lit les 2 boutons, envoie `J1` / `J2` sur le port serie, et recoit des commandes pour allumer ou eteindre les LED.

2. `app.py`
   Lance un serveur Flask, se connecte a l'Arduino en serie, gere les regles du jeu, et pousse les mises a jour en temps reel vers le navigateur.

Le front utilise:
- `templates/index.html`
- `static/app.js`
- `static/style.css`

## Modes de jeu

L'application inclut actuellement:

- `Timer Fantome`
  Chrono visible quelques instants puis masque. Le plus proche de la cible gagne.

- `Blackout`
  Variante encore plus dure et plus "scene", avec disparition tres rapide des reperes.

- `Double Impact`
  Chaque joueur doit faire 2 appuis. L'intervalle entre les 2 buzz doit coller a la cible.

- `Serie Royale`
  Best-of-3 sur un mode precision.

- `Reflex Noir`
  Attendre le signal `GO`. Faux depart sanctionne.

- `Rapid Fire`
  Serie reflexe rapide, premier a 3 points.

## Materiel et cablage

Le firmware actuel utilise ces broches:

- bouton joueur 1: pin `2`
- LED joueur 1: pin `5`
- bouton joueur 2: pin `10`
- LED joueur 2: pin `15`

Hypothese de cablage actuelle:

- les boutons sont en `INPUT_PULLUP`
- chaque bouton doit donc fermer vers `GND`
- les LED sont pilotees directement par les broches definies dans `arduino.cpp`

Important:
- la pin `15` depend de la carte Arduino utilisee
- sur certaines cartes, cela correspond a une broche analogique reutilisee en digital
- adapte `arduino.cpp` si ton hardware est different

## Protocole serie

Vitesse serie:

- `9600` bauds

Messages Arduino vers Python:

- `J1` quand le joueur 1 appuie
- `J2` quand le joueur 2 appuie

Messages Python vers Arduino:

- `A`: allume la LED du joueur 1
- `a`: eteint la LED du joueur 1
- `B`: allume la LED du joueur 2
- `b`: eteint la LED du joueur 2

## Installation locale

### 1. Creer le venv

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Installer les dependances Python

```bash
pip install flask pyserial
```

## Lancer l'application

Avec le venv actif:

```bash
python app.py
```

Ou directement:

```bash
./venv/bin/python app.py
```

Ensuite ouvre:

```text
http://127.0.0.1:5000
```

## Connexion Arduino

Par defaut, l'app essaie de se connecter a:

```text
/dev/cu.usbmodem101
```

Tu peux forcer le port avec:

```bash
ARDUINO_PORT=/dev/cu.usbmodemXXXX ./venv/bin/python app.py
```

Tu peux aussi changer le baudrate si besoin:

```bash
ARDUINO_BAUDRATE=9600 ./venv/bin/python app.py
```

L'application:
- detecte les ports `usbmodem`
- tue les processus qui bloquent le port avant ouverture
- bascule en mode simulation si aucun Arduino n'est disponible

## Controles interface

### Souris / tactile

- `Modes`: ouvre le menu des jeux
- `Plein ecran`: passe en fullscreen
- `Reset`: reinitialise le mode courant
- `Entrer en scene`: lance une manche

### Clavier

- `Espace` ou `Entree`: lancer la manche suivante
- `M`: ouvrir / fermer le menu des modes
- `F`: plein ecran
- `R`: reset du mode
- `Echap`: fermer le menu

En mode simulation sans Arduino:

- `A`: simuler un appui `J1`
- `L`: simuler un appui `J2`

## Anti-triche et perf

Le projet a ete pense pour eviter les fuites d'information pendant une manche:

- les scores ne sont pas affiches pendant le round
- les temps detailles restent masques jusqu'a la revelation
- le chrono visible est anime cote front pour plus de fluidite
- les changements d'etat sont pousses en temps reel via un flux serveur au lieu de poller `/api/state` en boucle

## Structure du projet

```text
.
├── app.py
├── arduino.cpp
├── templates/
│   └── index.html
├── static/
│   ├── app.js
│   └── style.css
└── README.md
```

## Firmware Arduino

Le fichier `arduino.cpp` contient la logique de base du buzzer. Selon ton workflow:

- soit tu l'ouvres dans l'Arduino IDE et tu l'adaptes en sketch
- soit tu l'integres dans ton environnement de build habituel

Pense a verifier:

- la carte selectionnee
- le bon port serie
- la compatibilite de la pin `15`

## Notes

- Le serveur Flask actuel est un serveur de dev, pratique pour la mise au point locale.
- Le projet est optimise pour macOS avec des ports du type `/dev/cu.usbmodem...`, mais la detection peut etre adaptee.
- Si ton cablage ou ta carte change, commence par mettre a jour `arduino.cpp`, puis ajuste les variables de connexion dans `app.py` si besoin.
