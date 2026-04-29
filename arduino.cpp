const int bouton1 = 2;
const int led1 = 5;

const int bouton2 = 10;
const int led2 = 15;

bool lastBouton1 = HIGH;
bool lastBouton2 = HIGH;

void setup() {
  pinMode(bouton1, INPUT_PULLUP);
  pinMode(led1, OUTPUT);

  pinMode(bouton2, INPUT_PULLUP);
  pinMode(led2, OUTPUT);

  Serial.begin(9600);
}

void loop() {
  bool etatBouton1 = digitalRead(bouton1);
  bool etatBouton2 = digitalRead(bouton2);

  if (etatBouton1 == LOW && lastBouton1 == HIGH) {
    Serial.println("J1");
  }

  if (etatBouton2 == LOW && lastBouton2 == HIGH) {
    Serial.println("J2");
  }

  lastBouton1 = etatBouton1;
  lastBouton2 = etatBouton2;

  if (Serial.available()) {
    char cmd = Serial.read();

    if (cmd == 'A') digitalWrite(led1, HIGH);
    if (cmd == 'a') digitalWrite(led1, LOW);

    if (cmd == 'B') digitalWrite(led2, HIGH);
    if (cmd == 'b') digitalWrite(led2, LOW);
  }

  delay(20);
}