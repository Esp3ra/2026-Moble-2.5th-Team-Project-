// First wiring check: sensor reads and LCD only. No actuator commands accepted.
#include <ArduinoJson.h>
#include <DHT.h>
#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <avr/wdt.h>

DHT dht(2, DHT11);
LiquidCrystal_I2C* screen = nullptr;
uint32_t sampledAt = 0;
uint8_t lcdAddress = 0;
bool i2cFault = false;

void lcdLine(uint8_t row, const char* text) {
  if (!screen) return;
  screen->setCursor(0, row);
  screen->print(text);
  for (uint8_t i = strlen(text); i < 20; ++i) screen->print(' ');
}

void setup() {
  MCUSR = 0;
  wdt_disable();
  Serial.begin(115200);
  // Motor/buzzer/RGB outputs remain high impedance. Keep external power OFF.
  const uint8_t outputs[] = {9, 10, 22, 24, 26, 28, 30};
  for (uint8_t pin : outputs) pinMode(pin, INPUT);
  dht.begin();
  Wire.begin();
  Wire.setWireTimeout(25000, true);
  uint8_t candidates = 0;
  for (uint8_t address = 1; address < 127; ++address) {
    Wire.beginTransmission(address);
    uint8_t error = Wire.endTransmission();
    if (Wire.getWireTimeoutFlag()) {
      i2cFault = true;
      Wire.clearWireTimeoutFlag();
    }
    if (error == 0) {
      Serial.print(F("{\"type\":\"i2c\",\"address\":"));
      Serial.print(address);
      Serial.print(F(",\"hex\":\"0x"));
      Serial.print(address, HEX);
      Serial.println(F("\"}"));
      if ((address >= 0x20 && address <= 0x27) || (address >= 0x38 && address <= 0x3f)) {
        lcdAddress = address;
        candidates++;
      }
    }
  }
  if (candidates == 1 && !i2cFault) {
    screen = new LiquidCrystal_I2C(lcdAddress, 20, 4);
    screen->init();
    screen->backlight();
    lcdLine(0, "MOBLE SENSOR CHECK");
    lcdLine(3, "ACTUATORS DISABLED");
  } else lcdAddress = 0;
  Serial.println(F("{\"type\":\"check_start\",\"actuators_enabled\":false,\"gas_units\":\"ADC_RAW_NOT_PPM\"}"));
  wdt_enable(WDTO_4S);
}

void loop() {
  wdt_reset();
  uint32_t now = millis();
  if (now - sampledAt < 2500) return;
  sampledAt = now;
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  int total = 0;
  for (uint8_t i = 0; i < 8; ++i) total += analogRead(A0);
  int gasRaw = total / 8;
  bool dhtOk = isfinite(temperature) && isfinite(humidity);
  StaticJsonDocument<384> doc;
  doc["type"] = "hardware_check";
  doc["uptime_ms"] = now;
  doc["dht_ok"] = dhtOk;
  if (isfinite(temperature)) doc["temperature"] = temperature; else doc["temperature"] = nullptr;
  if (isfinite(humidity)) doc["humidity"] = humidity; else doc["humidity"] = nullptr;
  doc["gas_raw"] = gasRaw;
  doc["gas_calibrated"] = false;
  doc["ir_raw"] = nullptr;
  doc["ir_used"] = false;
  doc["lcd_address"] = lcdAddress;
  doc["i2c_timeout"] = i2cFault;
  doc["actuators_enabled"] = false;
  serializeJson(doc, Serial);
  Serial.println();
  char line[21];
  if (dhtOk) snprintf(line, sizeof(line), "T:%2dC RH:%2d%%", (int)temperature, (int)humidity);
  else snprintf(line, sizeof(line), "DHT11: READ ERROR");
  lcdLine(1, line);
  snprintf(line, sizeof(line), "MQ9:%4d RAW", gasRaw);
  lcdLine(2, line);
  if (Wire.getWireTimeoutFlag()) {
    i2cFault = true;
    Wire.clearWireTimeoutFlag();
  }
}
