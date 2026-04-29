/*
 * Jeu de buzzer Arduino deux joueurs
 *
 * Protocole série (9600 baud) :
 *   Arduino → PC : "J1\n" quand le joueur 1 appuie
 *                  "J2\n" quand le joueur 2 appuie
 *   PC → Arduino : 'A' allume la LED joueur 1
 *                  'a' éteint  la LED joueur 1
 *                  'B' allume la LED joueur 2
 *                  'b' éteint  la LED joueur 2
 *
 * Câblage supposé :
 *   Bouton J1  → pin 2 (INPUT_PULLUP, actif bas)
 *   Bouton J2  → pin 3 (INPUT_PULLUP, actif bas)
 *   LED J1     → pin 8 (via résistance 220 Ω)
 *   LED J2     → pin 9 (via résistance 220 Ω)
 */

const int BTN1 = 2;
const int BTN2 = 3;
const int LED1 = 8;
const int LED2 = 9;

const unsigned long DEBOUNCE_MS = 30;

bool lastBtn1 = HIGH;
bool lastBtn2 = HIGH;
unsigned long lastDebounce1 = 0;
unsigned long lastDebounce2 = 0;
bool stableBtn1 = HIGH;
bool stableBtn2 = HIGH;

void setup() {
    Serial.begin(9600);
    pinMode(BTN1, INPUT_PULLUP);
    pinMode(BTN2, INPUT_PULLUP);
    pinMode(LED1, OUTPUT);
    pinMode(LED2, OUTPUT);
    digitalWrite(LED1, LOW);
    digitalWrite(LED2, LOW);
}

void handleLedCommands() {
    while (Serial.available() > 0) {
        char c = (char)Serial.read();
        switch (c) {
            case 'A': digitalWrite(LED1, HIGH); break;
            case 'a': digitalWrite(LED1, LOW);  break;
            case 'B': digitalWrite(LED2, HIGH); break;
            case 'b': digitalWrite(LED2, LOW);  break;
            default: break;
        }
    }
}

void readButton(int pin, bool &lastRaw, bool &stable, unsigned long &lastDebounce) {
    bool raw = digitalRead(pin);
    if (raw != lastRaw) {
        lastDebounce = millis();
        lastRaw = raw;
    }
    if ((millis() - lastDebounce) >= DEBOUNCE_MS) {
        if (raw != stable) {
            stable = raw;
            if (stable == LOW) {
                // Button pressed (active-low)
                if (pin == BTN1) Serial.println("J1");
                else              Serial.println("J2");
            }
        }
    }
}

void loop() {
    handleLedCommands();
    readButton(BTN1, lastBtn1, stableBtn1, lastDebounce1);
    readButton(BTN2, lastBtn2, stableBtn2, lastDebounce2);
}
