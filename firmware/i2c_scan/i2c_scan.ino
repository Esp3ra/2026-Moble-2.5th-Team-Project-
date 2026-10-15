#include <Wire.h>
void setup() {
  Wire.begin();
  Serial.begin(115200);
  Serial.println("Mega I2C scan: SDA=20, SCL=21");
}
void loop() {
  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) { Serial.print("Found 0x"); Serial.println(address, HEX); }
  }
  delay(3000);
}
