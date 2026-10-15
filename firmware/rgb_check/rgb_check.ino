// One RGB sequence per reset, then all channels OFF.
// User confirmed common cathode and onboard resistors. No servo/buzzer drive.
#include <Arduino.h>
#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <avr/wdt.h>

constexpr uint8_t RED = 26, GREEN = 22, BLUE = 24;
LiquidCrystal_I2C lcd(0x27, 20, 4);
bool lcdReady = false;
uint8_t step = 0;
uint32_t stepAt = 0;
bool done = false;
const char* colors[] = {"RED", "GREEN", "BLUE", "YELLOW"};

void rgb(bool red, bool green, bool blue) {
  digitalWrite(RED, red ? HIGH : LOW);
  digitalWrite(GREEN, green ? HIGH : LOW);
  digitalWrite(BLUE, blue ? HIGH : LOW);
}

void setup() {
  MCUSR = 0;
  wdt_disable();
  Serial.begin(115200);
  const uint8_t unusedOutputs[] = {9, 10, 28, 30};
  for (uint8_t pin : unusedOutputs) pinMode(pin, INPUT);
  const uint8_t channels[] = {RED, GREEN, BLUE};
  for (uint8_t pin : channels) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  Wire.begin();
  Wire.setWireTimeout(25000, true);
  Wire.beginTransmission(0x27);
  lcdReady = Wire.endTransmission() == 0;
  if (lcdReady) {
    lcd.init();
    lcd.backlight();
    lcd.setCursor(0, 0); lcd.print(F("MOBLE RGB CHECK"));
    lcd.setCursor(0, 1); lcd.print(F("Starts in 5 seconds"));
    lcd.setCursor(0, 3); lcd.print(F("MOTORS NOT DRIVEN"));
  }
  stepAt = millis();
  Serial.println(F("{\"type\":\"rgb_check_start\",\"servo_drive\":false,\"buzzer_drive\":false}"));
  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  if (done || millis() - stepAt < (step == 0 ? 5000UL : 1200UL)) return;
  stepAt = millis();
  if (step < 4) {
    rgb(step == 0 || step == 3, step == 1 || step == 3, step == 2);
    Serial.print(F("{\"type\":\"rgb_step\",\"color\":\""));
    Serial.print(colors[step]); Serial.println(F("\"}"));
    if (lcdReady) {
      lcd.setCursor(0, 1); lcd.print(F("                    "));
      lcd.setCursor(0, 1); lcd.print(colors[step]);
    }
    ++step;
  } else {
    rgb(false, false, false);
    done = true;
    Serial.println(F("{\"type\":\"rgb_check_done\",\"rgb_on\":false}"));
    if (lcdReady) {
      lcd.setCursor(0, 1); lcd.print(F("DONE - RGB OFF      "));
    }
  }
}
