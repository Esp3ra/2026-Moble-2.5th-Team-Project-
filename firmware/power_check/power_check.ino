// Bounded simultaneous bench test. No actuator movement on boot.
// LOAD requires host '!' heartbeat at least every 1.5s; STOP always stops.
// LOAD: 3 pairs (6s). LOAD10/LOAD30: 5/15 pairs. Always stops automatically.
// LCD backlight stays ON; this backpack API provides no brightness PWM.
#include <ArduinoJson.h>
#include <DHT.h>
#include <Servo.h>
#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <avr/wdt.h>

DHT dht(2, DHT11);
Servo vent, rotation;
LiquidCrystal_I2C lcd(0x27, 20, 4);
bool lcdReady = false, i2cFault = false, active = false, droppingLine = false;
float temperature = NAN, humidity = NAN;
uint32_t sampledAt = 0, reportedAt = 0, changedAt = 0, startedAt = 0, pingAt = 0;
uint8_t step = 0, used = 0, lcdProbeAttempts = 0;
uint8_t pairs = 3;
char command[20];
char phaseLabel[21];
const uint8_t rgbPins[] = {22, 24, 26};
const uint8_t idlePins[] = {9, 10, 28, 30};
const char* phase = "IDLE";

void lcdLine(uint8_t row, const char* value) {
  if (!lcdReady) return;
  lcd.setCursor(0, row);
  lcd.print(value);
  for (uint8_t i = strlen(value); i < 20; ++i) lcd.print(' ');
}

void report(const char* value) {
  phase = value;
  Serial.print(F("{\"type\":\"power_phase\",\"phase\":\""));
  Serial.print(value);
  Serial.print(F("\",\"uptime_ms\":")); Serial.print(millis());
  Serial.println(F("}"));
  lcdLine(1, value);
}

void stopAll(const char* reason) {
  if (rotation.attached()) rotation.writeMicroseconds(1500);
  if (vent.attached()) vent.write(90);
  noTone(28);
  digitalWrite(28, LOW); pinMode(28, INPUT);
  for (uint8_t pin : rgbPins) digitalWrite(pin, LOW);
  if (rotation.attached() || vent.attached()) delay(250);
  rotation.detach(); vent.detach();
  pinMode(9, INPUT); pinMode(10, INPUT);
  active = false;
  report(reason);
  lcdLine(3, "BACKLIGHT ON / IDLE");
}

void beginLoad(uint8_t requestedPairs) {
  if (active) return; // Do not extend a running test with repeated LOAD commands.
  if (!lcdReady || i2cFault || !isfinite(temperature) || !isfinite(humidity)) {
    stopAll("SENSOR NOT READY"); return;
  }
  step = 0;
  pairs = requestedPairs;
  startedAt = changedAt = pingAt = millis();
  active = true;
  rotation.writeMicroseconds(1500); rotation.attach(10);
  vent.write(90); vent.attach(9);
  for (uint8_t pin : rgbPins) digitalWrite(pin, HIGH);
  tone(28, 2000);
  lcdLine(3, "BL ON RGB WHITE 2kHz");
  vent.write(75); rotation.writeMicroseconds(1600);
  snprintf(phaseLabel, sizeof(phaseLabel), "LOAD 1/%u D9=75", pairs);
  report(phaseLabel);
}

void acceptCommand() {
  if (strcmp(command, "PING") == 0) pingAt = millis();
  else if (strcmp(command, "LOAD") == 0) beginLoad(3);
  else if (strcmp(command, "LOAD10") == 0) beginLoad(5);
  else if (strcmp(command, "LOAD30") == 0) beginLoad(15);
  else if (strcmp(command, "STOP") == 0) stopAll("STOPPED");
  else {
    stopAll("BAD COMMAND");
    Serial.print(F("{\"type\":\"command_rejected\",\"hex\":\""));
    for (uint8_t i = 0; command[i]; ++i) {
      if ((uint8_t)command[i] < 16) Serial.print('0');
      Serial.print((uint8_t)command[i], HEX);
    }
    Serial.println(F("\"}"));
  }
}

void setup() {
  MCUSR = 0; wdt_disable();
  Serial.begin(115200);
  for (uint8_t pin : idlePins) pinMode(pin, INPUT);
  for (uint8_t pin : rgbPins) {
    digitalWrite(pin, LOW); pinMode(pin, OUTPUT);
  }
  dht.begin();
  Wire.begin(); Wire.setWireTimeout(25000, true);
  // Allow a backpack already running across a USB reset to settle. Retry only
  // during startup; any timeout during the active load still stops the test.
  for (uint8_t attempt = 0; attempt < 3 && !lcdReady; ++attempt) {
    delay(100);
    Wire.clearWireTimeoutFlag();
    Wire.beginTransmission(0x27);
    lcdReady = Wire.endTransmission() == 0 && !Wire.getWireTimeoutFlag();
    ++lcdProbeAttempts;
  }
  i2cFault = !lcdReady;
  Wire.clearWireTimeoutFlag();
  if (lcdReady) {
    lcd.init(); lcd.backlight();
    lcdLine(0, "MOBLE POWER CHECK");
    lcdLine(3, "BACKLIGHT ON / IDLE");
  }
  report("READY / NO DRIVE");
  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  uint8_t budget = 32;
  while (Serial.available() && budget--) {
    char c = Serial.read();
    // DHT reads briefly mask interrupts. A lost heartbeat byte can be retried
    // without turning a partially received multi-byte PING into a command.
    if (c == '!') { pingAt = millis(); continue; }
    if (c == '\n') {
      if (!droppingLine) { command[used] = '\0'; acceptCommand(); }
      used = 0; droppingLine = false;
    } else if (c != '\r' && !droppingLine) {
      if (used < sizeof(command) - 1) command[used++] = c;
      else { used = 0; droppingLine = true; stopAll("OVERFLOW"); }
    }
  }
  uint32_t now = millis();
  if (active && (now - pingAt > 1500 || now - startedAt > (uint32_t)pairs * 2000 + 2000)) {
    stopAll("TIMEOUT STOP");
  }
  if (active && now - changedAt >= 1000) {
    changedAt = now;
    ++step;
    if (step >= pairs * 2) stopAll("LOAD DONE");
    else if (step % 2) {
      vent.write(90); rotation.writeMicroseconds(1500);
      snprintf(phaseLabel, sizeof(phaseLabel), "REST %u/%u D9=90", step / 2 + 1, pairs);
      report(phaseLabel);
    } else {
      uint8_t angle = (step / 2) % 2 ? 105 : 75;
      vent.write(angle); rotation.writeMicroseconds(1600);
      snprintf(phaseLabel, sizeof(phaseLabel), "LOAD %u/%u D9=%u", step / 2 + 1, pairs, angle);
      report(phaseLabel);
    }
  }
  if (now - sampledAt >= 2500) {
    sampledAt = now;
    temperature = dht.readTemperature(); humidity = dht.readHumidity();
    char line[21];
    if (isfinite(temperature) && isfinite(humidity))
      snprintf(line, sizeof(line), "T:%2dC RH:%2d%%", (int)temperature, (int)humidity);
    else snprintf(line, sizeof(line), "DHT READ ERROR");
    lcdLine(2, line);
    if (active && (!isfinite(temperature) || !isfinite(humidity))) stopAll("DHT ERROR STOP");
  }
  if (Wire.getWireTimeoutFlag()) {
    i2cFault = true; Wire.clearWireTimeoutFlag();
    if (active) stopAll("I2C ERROR STOP");
  }
  if (now - reportedAt >= 500) {
    reportedAt = now;
    StaticJsonDocument<384> doc;
    doc["type"] = "power_check"; doc["uptime_ms"] = millis();
    doc["phase"] = phase; doc["active"] = active;
    doc["dht_ok"] = isfinite(temperature) && isfinite(humidity);
    doc["temperature"] = temperature; doc["humidity"] = humidity;
    doc["gas_raw"] = analogRead(A0); doc["gas_calibrated"] = false;
    doc["lcd_ready"] = lcdReady; doc["i2c_timeout"] = i2cFault;
    doc["backlight_on"] = lcdReady;
    doc["lcd_probe_attempts"] = lcdProbeAttempts;
    serializeJson(doc, Serial); Serial.println();
  }
}
