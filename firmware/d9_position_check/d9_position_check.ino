// D9-only positioning check. External regulated 5V supply and common GND.
// No motion at boot. CLOSE drives 0 degrees; OPEN drives 90 degrees for 2s,
// then releases the servo signal. A response confirms the command, not angle.
#include <Arduino.h>
#include <Servo.h>
#include <avr/wdt.h>

Servo vent;
char input[12];
uint8_t used = 0;
uint8_t requestedAngle = 0;
bool dropping = false, driving = false;
uint32_t startedAt = 0;

void report(const char* state) {
  Serial.print(F("{\"type\":\"d9_check\",\"pin\":9,\"requested_angle\":"));
  Serial.print(requestedAngle);
  Serial.print(F(",\"state\":\""));
  Serial.print(state);
  Serial.println(F("\",\"physical_feedback\":false}"));
}

void releaseServo() {
  if (vent.attached()) vent.detach();
  pinMode(9, INPUT);
  driving = false;
}

void execute() {
  if ((strcmp(input, "CLOSE") == 0 || strcmp(input, "OPEN") == 0) && !driving) {
    requestedAngle = strcmp(input, "OPEN") == 0 ? 90 : 0;
    vent.write(requestedAngle);
    vent.attach(9);
    startedAt = millis();
    driving = true;
    report(requestedAngle == 0 ? "DRIVING_ZERO" : "DRIVING_NINETY");
  } else if (strcmp(input, "STOP") == 0) {
    releaseServo();
    report("RELEASED");
  } else if (strcmp(input, "STATUS") == 0) {
    report(driving ? (requestedAngle == 0 ? "DRIVING_ZERO" : "DRIVING_NINETY") : "READY_RELEASED");
  } else {
    releaseServo();
    report("BAD_COMMAND_RELEASED");
  }
}

void setup() {
  MCUSR = 0;
  wdt_disable();
  pinMode(9, INPUT);
  Serial.begin(115200);
  report("READY_RELEASED");
  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  uint8_t budget = 32;
  while (Serial.available() && budget--) {
    char c = Serial.read();
    if (c == '\n') {
      if (!dropping && used) {
        input[used] = '\0';
        execute();
      }
      used = 0;
      dropping = false;
    } else if (c != '\r' && !dropping) {
      if (used < sizeof(input) - 1) input[used++] = c;
      else {
        dropping = true;
        releaseServo();
        report("OVERFLOW_RELEASED");
      }
    }
  }
  if (driving && millis() - startedAt >= 2000) {
    releaseServo();
    report(requestedAngle == 0 ? "ZERO_COMMAND_COMPLETE_RELEASED" : "NINETY_COMMAND_COMPLETE_RELEASED");
  }
}
