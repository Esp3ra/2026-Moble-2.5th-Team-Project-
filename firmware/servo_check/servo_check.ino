// Bench checks only. No movement at boot; each sequence requires a command.
// Use the user's separate regulated 5V supply, with a common Mega GND.
// VENT: 90/75/105/90 degrees. NEUTRAL: 1500 us. RUN: brief 1600 us then 1500 us.
// ONESEC: three 1600/1500 us pairs, one second at each setting.
// RUN is for use only after the physical neutral has been checked by a person.
#include <Arduino.h>
#include <Servo.h>
#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <avr/wdt.h>

Servo vent, rotation;
LiquidCrystal_I2C lcd(0x27, 20, 4);
bool lcdReady = false;
bool droppingLine = false;
char command[20];
uint8_t used = 0, sequence = 0, step = 0;
uint32_t changedAt = 0;

void report(const char* state) {
  Serial.print(F("{\"type\":\"servo_check\",\"state\":\""));
  Serial.print(state); Serial.println(F("\"}"));
  if (lcdReady) {
    lcd.setCursor(0, 1); lcd.print(F("                    "));
    lcd.setCursor(0, 1); lcd.print(state);
  }
}

void stopAll() {
  if (rotation.attached()) {
    rotation.writeMicroseconds(1500);
    delay(250); // Allow several neutral pulses before restoring idle pins.
    rotation.detach();
  }
  if (vent.attached()) vent.detach();
  pinMode(9, INPUT); pinMode(10, INPUT);
  sequence = 0;
}

void start(const char* name) {
  stopAll();
  step = 0;
  changedAt = millis();
  if (strcmp(name, "VENT") == 0) {
    sequence = 1;
    vent.writeMicroseconds(1500); vent.attach(9);
    report("D9 VENT 90 DEG");
  } else if (strcmp(name, "NEUTRAL") == 0) {
    sequence = 2;
    rotation.writeMicroseconds(1500); rotation.attach(10);
    report("D10 NEUTRAL 1500");
  } else if (strcmp(name, "RUN") == 0 || strcmp(name, "ONESEC") == 0) {
    sequence = strcmp(name, "ONESEC") == 0 ? 4 : 3;
    rotation.writeMicroseconds(1500); rotation.attach(10);
    report("D10 NEUTRAL 1500");
  } else if (strcmp(name, "STOP") == 0) report("STOPPED / INPUT");
  else report("BAD COMMAND / STOP");
}

void setup() {
  MCUSR = 0; wdt_disable();
  Serial.begin(115200);
  const uint8_t outputs[] = {9, 10, 22, 24, 26, 28, 30};
  for (uint8_t pin : outputs) pinMode(pin, INPUT);
  Wire.begin(); Wire.setWireTimeout(25000, true);
  Wire.beginTransmission(0x27); lcdReady = Wire.endTransmission() == 0;
  if (lcdReady) {
    lcd.init(); lcd.backlight();
    lcd.setCursor(0, 0); lcd.print(F("MOBLE SERVO CHECK"));
    lcd.setCursor(0, 3); lcd.print(F("SEPARATE 5V SUPPLY"));
  }
  report("READY / NO DRIVE");
  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  uint8_t budget = 32;
  while (Serial.available() && budget--) {
    char c = Serial.read();
    if (c == '\n') {
      if (!droppingLine) { command[used] = '\0'; start(command); }
      used = 0; droppingLine = false;
    } else if (c != '\r' && !droppingLine) {
      if (used < sizeof(command) - 1) command[used++] = c;
      else { used = 0; droppingLine = true; stopAll(); report("OVERFLOW / STOP"); }
    }
  }
  uint32_t elapsed = millis() - changedAt;
  if (sequence == 1 && elapsed >= 1000) {
    changedAt = millis();
    if (++step == 1) { vent.write(75); report("D9 VENT 75 DEG"); }
    else if (step == 2) { vent.write(105); report("D9 VENT 105 DEG"); }
    else if (step == 3) { vent.write(90); report("D9 VENT 90 DEG"); }
    else { stopAll(); report("VENT DONE"); }
  } else if (sequence == 2 && elapsed >= 3000) {
    stopAll(); report("NEUTRAL DONE");
  } else if (sequence == 4 && elapsed >= 1000) {
    changedAt = millis();
    ++step;
    if (step > 6) { stopAll(); report("ONESEC DONE"); }
    else if (step % 2 == 1) {
      rotation.writeMicroseconds(1600);
      report(step == 1 ? "D10 RUN 1/3 1600" : step == 3 ? "D10 RUN 2/3 1600" : "D10 RUN 3/3 1600");
    } else {
      rotation.writeMicroseconds(1500);
      report(step == 2 ? "D10 STOP 1/3 1500" : step == 4 ? "D10 STOP 2/3 1500" : "D10 STOP 3/3 1500");
    }
  } else if (sequence == 3) {
    if (step == 0 && elapsed >= 1000) {
      step = 1; changedAt = millis();
      rotation.writeMicroseconds(1600); report("D10 RUN 1600 US");
    } else if (step == 1 && elapsed >= 600) {
      step = 2; changedAt = millis();
      rotation.writeMicroseconds(1500); report("D10 STOP 1500 US");
    } else if (step == 2 && elapsed >= 2000) {
      stopAll(); report("RUN DONE");
    }
  }
}
