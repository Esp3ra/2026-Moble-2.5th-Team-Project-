// One-shot test for the wired 5V three-pin MH-FMD module.
// Default: 1/2 kHz tone, verified audible by the user. Set BUZZER_TEST_TONE=0
// for the original HIGH/LOW comparison, which was silent on this module.
// Motor and RGB pins are never driven. A listener must identify the sound phase.
#include <Arduino.h>
#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <avr/wdt.h>

#ifndef BUZZER_TEST_TONE
#define BUZZER_TEST_TONE 1
#endif

constexpr uint8_t BUZZER = 28;
LiquidCrystal_I2C lcd(0x27, 20, 4);
bool lcdReady = false, done = false;
uint8_t step = 0;
uint32_t stepAt = 0;

void show(const char* phase) {
  Serial.print(F("{\"type\":\"buzzer_phase\",\"phase\":\""));
  Serial.print(phase); Serial.println(F("\"}"));
  if (lcdReady) {
    lcd.setCursor(0, 1); lcd.print(F("                    "));
    lcd.setCursor(0, 1); lcd.print(phase);
  }
}

void idle() {
  noTone(BUZZER);
  pinMode(BUZZER, INPUT);
  digitalWrite(BUZZER, LOW); // Disable the internal pull-up as in sensor check.
}

void setup() {
  MCUSR = 0;
  wdt_disable();
  Serial.begin(115200);
  const uint8_t pins[] = {9, 10, 22, 24, 26, 28, 30};
  for (uint8_t pin : pins) pinMode(pin, INPUT);
  idle();
  Wire.begin();
  Wire.setWireTimeout(25000, true);
  Wire.beginTransmission(0x27);
  lcdReady = Wire.endTransmission() == 0;
  if (lcdReady) {
    lcd.init(); lcd.backlight();
    lcd.setCursor(0, 0); lcd.print(F("MOBLE BUZZER CHECK"));
    lcd.setCursor(0, 1); lcd.print(F("Starts in 5 seconds"));
    lcd.setCursor(0, 3); lcd.print(F("MOTORS NOT DRIVEN"));
  }
  stepAt = millis();
  Serial.println(F("{\"type\":\"buzzer_check_start\",\"servo_drive\":false}"));
  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  if (done || millis() - stepAt < (step == 0 ? 5000UL : 2500UL)) return;
  stepAt = millis();
  if (step == 0) {
#if BUZZER_TEST_TONE
    show("TONE 1000 Hz");
    tone(BUZZER, 1000);
#else
    show("HIGH / D28 = 5V");
    digitalWrite(BUZZER, HIGH); pinMode(BUZZER, OUTPUT);
#endif
  } else if (step == 1) {
    idle(); show("INPUT / IDLE");
  } else if (step == 2) {
#if BUZZER_TEST_TONE
    show("TONE 2000 Hz");
    tone(BUZZER, 2000);
#else
    show("LOW / D28 = 0V");
    digitalWrite(BUZZER, LOW); pinMode(BUZZER, OUTPUT);
#endif
  } else {
    idle(); show("DONE / INPUT IDLE");
    done = true;
    Serial.println(F("{\"type\":\"buzzer_check_done\",\"pin_mode\":\"INPUT\"}"));
  }
  ++step;
}
