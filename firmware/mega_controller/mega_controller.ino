// Jetson + Mega educational monitoring controller, JSON Lines protocol v1.
// On every fault: device OFF. Ventilation and sensor alarms remain independent.
#include <ArduinoJson.h>
#include <DHT.h>
#include <LiquidCrystal_I2C.h>
#include <Servo.h>
#include <Wire.h>
#include <avr/wdt.h>
#include "hardware_config.h"
#include "output_policy.h"
#include "bench_policy.h"
#include "ventilation_policy.h"
#include "ventilation_indicators.h"

DHT dht(DHT_PIN, DHT11);
LiquidCrystal_I2C lcd(LCD_ADDRESS, LCD_COLUMNS, LCD_ROWS);
Servo ventServo;
Servo rotationServo;
BenchRunLimit runLimit;
char lineBuffer[384];
size_t lineLength = 0;
bool droppingLine = false;
float temperature = NAN, humidity = NAN;
int gasRaw = -1;
bool sensorOk = false, localDanger = false;
bool localTempAlert = false, localGasAlert = false;
bool localTempDanger = false;
TemperatureStop temperatureStop;
bool hostTemperatureStop = false;
bool lastCommandEnable = false, settingsLocked = true;
bool accessAlert = false, emergencyStopped = false, alarmAcknowledged = false;
const char* ventMode = "AUTO";
bool deviceEnabled = false;
bool lcdReady = false;
uint32_t sampleAt = 0, telemetryAt = 0, commandAt = 0, lcdAt = 0;
uint32_t telemetrySeq = 0, lastSeq = 0, activeSession = 0;
bool haveCommand = false;
const char* currentState = "FAULT";
const char* currentVent = "SAFE";
const char* currentFan = "OFF";
const char* faultReason = "STARTUP";

bool hardwareReady() {
  return WIRING_CONFIRMED && ENABLE_DHT && ENABLE_GAS
      && (ENABLE_DEVICE_OUTPUT || ENABLE_ROTATION_SERVO)
      && (!ENABLE_ROTATION_SERVO || ROTATION_CALIBRATED)
      && ENABLE_BUZZER && BUZZER_DRIVE_CONFIRMED
      && (!ENABLE_LCD || lcdReady)
      && GAS_MODEL_CONFIRMED
      && (BENCH_MODE || VENTILATION_MODE || (GAS_WARMUP_MS > 0 && (!ENABLE_SERVO || VENT_CALIBRATED)));
}

void deviceOff() {
  deviceEnabled = false;
  currentFan = "OFF";
  if (WIRING_CONFIRMED && ENABLE_DEVICE_OUTPUT) digitalWrite(DEVICE_ENABLE_PIN, DEVICE_OFF_LEVEL);
  if (rotationServo.attached()) rotationServo.writeMicroseconds(ROTATION_STOP_US);
}

void applyOutputs(const char* state, const char* vent, bool beep, bool enableDevice) {
  if (VENTILATION_MODE) {
    VentilationPlan plan = planVentilation(state, localDanger, sensorOk && hardwareReady(), enableDevice,
                                           ROTATION_STOP_US, FAN_LOW_US, FAN_HIGH_US,
                                           settingsLocked ? "AUTO" : ventMode, emergencyStopped,
                                           temperatureStop.active || hostTemperatureStop);
    currentState = plan.state;
    currentVent = plan.vent;
    currentFan = plan.fan;
    deviceEnabled = plan.enabled;
    if (rotationServo.attached()) rotationServo.writeMicroseconds(plan.pulseUs);
    if (ventServo.attached()) {
      if (strcmp(plan.vent, "OPEN") == 0) ventServo.write(VENT_OPEN_ANGLE);
      else if (strcmp(plan.vent, "CLOSED") == 0) ventServo.write(VENT_CLOSED_ANGLE);
    }
    return;
  }
  currentState = state;
  currentVent = vent;
  OutputPlan output = planOutputs(state, sensorOk, hardwareReady(), beep, enableDevice,
                                  ROTATION_STOP_US, ROTATION_RUN_US);
  deviceEnabled = output.deviceEnabled;
  if (BENCH_MODE && (strcmp(state, "DANGER") == 0 || strcmp(state, "FAULT") == 0)) runLimit.trip();
  if (!WIRING_CONFIRMED) { deviceEnabled = false; return; }
  if (ENABLE_DEVICE_OUTPUT) digitalWrite(DEVICE_ENABLE_PIN, deviceEnabled ? DEVICE_ACTIVE_LEVEL : DEVICE_OFF_LEVEL);
  if (ENABLE_ROTATION_SERVO && rotationServo.attached()) rotationServo.writeMicroseconds(output.rotationUs);
  if (ENABLE_STATUS_LEDS) {
    digitalWrite(GREEN_LED_PIN, activeOutput(output.green, !RGB_COMMON_ANODE));
    digitalWrite(BLUE_LED_PIN, activeOutput(output.blue, !RGB_COMMON_ANODE));
    digitalWrite(RED_LED_PIN, activeOutput(output.red, !RGB_COMMON_ANODE));
  }
  if (ENABLE_BUZZER && BUZZER_DRIVE_CONFIRMED) {
    if (BUZZER_ACTIVE) digitalWrite(BUZZER_PIN, activeOutput(output.buzzer, BUZZER_ACTIVE_LEVEL == HIGH));
    else if (output.buzzer) tone(BUZZER_PIN, 2000);
    else noTone(BUZZER_PIN);
  }
  if (ENABLE_SERVO && ventServo.attached()) {
    if (strcmp(vent, "OPEN") == 0) ventServo.write(VENT_OPEN_ANGLE);
    else if (strcmp(vent, "PARTIAL") == 0) ventServo.write(VENT_PARTIAL_ANGLE);
    else if (strcmp(vent, "CLOSED") == 0) ventServo.write(VENT_CLOSED_ANGLE);
    else if (MOVE_VENT_ON_FAULT) ventServo.write(VENT_FAULT_ANGLE);
  }
}

void fault(const char* reason) {
  if (strcmp(reason, "COMM_ERROR") == 0) alarmAcknowledged = false;
  faultReason = reason;
  lastCommandEnable = false;
  applyOutputs("FAULT", localDanger ? "OPEN" : "SAFE", true, false);
}

void readSensors(uint32_t now) {
  bool previousTempAlert = localTempAlert, previousGasAlert = localGasAlert;
  if (ENABLE_DHT) {
    temperature = dht.readTemperature();
    humidity = dht.readHumidity();
  }
  gasRaw = ENABLE_GAS ? analogRead(GAS_PIN) : -1;
  bool warm = BENCH_MODE || VENTILATION_MODE || (GAS_WARMUP_MS > 0 && now >= GAS_WARMUP_MS);
  sensorOk = ENABLE_DHT && ENABLE_GAS && GAS_MODEL_CONFIRMED && warm
      && isfinite(temperature) && temperature >= 0 && temperature <= 50
      && isfinite(humidity) && humidity >= 0 && humidity <= 100 && gasRaw > 2 && gasRaw < 1021;
  if (VENTILATION_MODE)
    temperatureStop.update(temperature, sensorOk && hardwareReady(), now,
                           FAN_TEMP_RED_C, FAN_TEMP_RELEASE_C, FAN_TEMP_RESTART_MS);
  if (sensorOk) {
    if (VENTILATION_MODE) {
      uint8_t temperatureLevel = ventilationTemperatureLevel(temperature, FAN_TEMP_TRIP_C, FAN_TEMP_RED_C);
      localTempAlert = temperatureLevel > 0;
      localTempDanger = temperatureLevel == 2;
      if (gasRaw >= FAN_GAS_TRIP_RAW) localGasAlert = true;
      else if (gasRaw < FAN_GAS_RELEASE_RAW) localGasAlert = false;
      localDanger = localTempAlert || localGasAlert || temperatureStop.active;
      if ((localTempAlert && !previousTempAlert) || (localGasAlert && !previousGasAlert))
        alarmAcknowledged = false;
    } else {
      if (temperature >= TEMP_DANGER_C || (!BENCH_MODE && gasRaw >= GAS_DANGER_RAW)) localDanger = true;
      else if (temperature < TEMP_RECOVER_C && (BENCH_MODE || gasRaw < GAS_RECOVER_RAW)) localDanger = false;
    }
  }
  if (!sensorOk) fault("SENSOR_ERROR");
  else if (localDanger) {
    if (VENTILATION_MODE) {
      // A local warning can boost a permitted fan, never clear a host/MCU fault.
      if (haveCommand && now - commandAt < HOST_TIMEOUT_MS && strcmp(currentState, "FAULT") != 0)
        applyOutputs("WARNING", "OPEN", true, lastCommandEnable);
    } else applyOutputs("DANGER", "OPEN", true, false);
  }
}

void emitTelemetry(uint32_t now) {
  StaticJsonDocument<768> doc;
  doc["v"] = 1;
  doc["type"] = "telemetry";
  doc["seq"] = telemetrySeq++;
  doc["uptime_ms"] = now;
  if (isfinite(temperature)) doc["temperature"] = temperature; else doc["temperature"] = nullptr;
  if (isfinite(humidity)) doc["humidity"] = humidity; else doc["humidity"] = nullptr;
  if (gasRaw >= 0) doc["gas_raw"] = gasRaw; else doc["gas_raw"] = nullptr;
  if (ENABLE_IR) doc["ir_detected"] = (digitalRead(IR_PIN) == (IR_ACTIVE_LOW ? LOW : HIGH));
  else doc["ir_detected"] = nullptr;
  doc["sensor_ok"] = sensorOk;
  doc["hardware_ready"] = hardwareReady();
  doc["profile"] = VENTILATION_MODE ? "ventilation" : BENCH_MODE ? "bench" : "production";
  doc["gas_guard"] = !BENCH_MODE && !VENTILATION_MODE;
  doc["bench_run_ms"] = BENCH_MODE ? 10000 : 0;
  if (VENTILATION_MODE) {
    doc["policy_rev"] = 6;
    doc["temp_restart_ms"] = FAN_TEMP_RESTART_MS;
    doc["temperature_stop"] = temperatureStop.active || hostTemperatureStop;
    doc["local_temperature_stop"] = temperatureStop.active;
    doc["buzzer_duty_percent"] = BUZZER_DUTY_PERCENT;
    doc["gas_mode"] = "raw_demo";
    doc["temp_trip"] = FAN_TEMP_TRIP_C;
    doc["gas_trip"] = FAN_GAS_TRIP_RAW;
    doc["temp_release"] = FAN_TEMP_RELEASE_C;
    doc["temp_red"] = FAN_TEMP_RED_C;
    doc["temperature_danger"] = localTempDanger;
    doc["gas_release"] = FAN_GAS_RELEASE_RAW;
    doc["fan"] = currentFan;
    doc["environment_alert"] = localDanger;
    doc["settings_locked"] = settingsLocked;
    doc["access_alert"] = accessAlert;
    doc["emergency_stop"] = emergencyStopped;
    doc["vent_mode"] = ventMode;
    doc["alarm_acknowledged"] = alarmAcknowledged;
  }
  doc["state"] = currentState;
  doc["vent"] = currentVent;
  doc["device_enable"] = deviceEnabled;
  doc["fault"] = faultReason;
  serializeJson(doc, Serial);
  Serial.println();
}

void emitAck(uint32_t seq, uint32_t session, bool accepted) {
  StaticJsonDocument<512> doc;
  doc["v"] = 1;
  doc["type"] = "ack";
  doc["seq"] = seq;
  doc["session"] = session;
  doc["accepted"] = accepted;
  doc["state"] = currentState;
  doc["vent"] = currentVent;
  doc["device_enable"] = deviceEnabled;
  doc["fault"] = faultReason;
  if (VENTILATION_MODE) {
    doc["profile"] = "ventilation";
    doc["temperature_stop"] = temperatureStop.active || hostTemperatureStop;
    doc["fan"] = currentFan;
    doc["environment_alert"] = localDanger;
    doc["settings_locked"] = settingsLocked;
    doc["access_alert"] = accessAlert;
    doc["emergency_stop"] = emergencyStopped;
    doc["vent_mode"] = ventMode;
    doc["alarm_acknowledged"] = alarmAcknowledged;
  }
  serializeJson(doc, Serial);
  Serial.println();
}

void processLine(uint32_t now) {
  StaticJsonDocument<768> doc;
  DeserializationError error = deserializeJson(doc, lineBuffer);
  if (error || doc["v"].as<int>() != 1 || strcmp(doc["type"] | "", "command") != 0
      || !doc["seq"].is<uint32_t>() || !doc["session"].is<uint32_t>()
      || !doc["device_enable"].is<bool>() || !doc["buzzer"].is<bool>()) {
    fault("BAD_COMMAND"); return;
  }
  uint32_t seq = doc["seq"], session = doc["session"];
  const char* requestedState = doc["state"] | "";
  const char* requestedVent = doc["vent"] | "";
  bool normal = strcmp(requestedState, "NORMAL") == 0;
  bool warning = strcmp(requestedState, "WARNING") == 0;
  bool danger = strcmp(requestedState, "DANGER") == 0;
  bool isFault = strcmp(requestedState, "FAULT") == 0;
  const char* state = normal ? "NORMAL" : warning ? "WARNING" : danger ? "DANGER" : "FAULT";
  bool closed = strcmp(requestedVent, "CLOSED") == 0;
  bool partial = strcmp(requestedVent, "PARTIAL") == 0;
  bool open = strcmp(requestedVent, "OPEN") == 0;
  bool safe = strcmp(requestedVent, "SAFE") == 0;
  const char* vent = closed ? "CLOSED" : partial ? "PARTIAL" : open ? "OPEN" : "SAFE";
  if ((!normal && !warning && !danger && !isFault) || (!closed && !partial && !open && !safe) || session == 0) {
    fault("BAD_COMMAND"); emitAck(seq, session, false); return;
  }
  bool newSession = activeSession != session;
  if (VENTILATION_MODE) {
    const char* fan = doc["fan"] | "";
    const char* mode = doc["vent_mode"] | "";
    bool run = doc["device_enable"].as<bool>();
    if (strcmp(doc["profile"] | "", "ventilation") != 0 || !doc["settings_locked"].is<bool>() || !doc["access_alert"].is<bool>()
        || !doc["emergency_stop"].is<bool>() || !doc["alarm_acknowledged"].is<bool>()
        || !doc["temperature_stop"].is<bool>()
        || (doc["temperature_stop"].as<bool>() && (run || !closed))
        || (strcmp(mode, "AUTO") != 0 && strcmp(mode, "OPEN") != 0 && strcmp(mode, "CLOSED") != 0)
        || (doc["emergency_stop"].as<bool>() && (run || !closed))
        || (run && strcmp(fan, warning ? "HIGH" : "LOW") != 0)
        || (!run && strcmp(fan, "OFF") != 0) || (run && isFault)) {
      fault("BAD_FAN_COMMAND"); emitAck(seq, session, false); return;
    }
  }
  if (!newSession && haveCommand && (int32_t)(seq - lastSeq) <= 0) {
    fault("REPLAY_COMMAND"); emitAck(seq, session, false); return;
  }
  if (newSession && doc["device_enable"].as<bool>()) {
    fault("SESSION_NOT_ARMED"); emitAck(seq, session, false); return;
  }
  activeSession = session;
  lastSeq = seq;
  commandAt = now;
  haveCommand = true;
  faultReason = "";
  bool requestedRun = doc["device_enable"].as<bool>();
  lastCommandEnable = requestedRun;
  if (VENTILATION_MODE) settingsLocked = doc["settings_locked"].as<bool>();
  if (VENTILATION_MODE) accessAlert = doc["access_alert"].as<bool>();
  if (VENTILATION_MODE) {
    emergencyStopped = doc["emergency_stop"].as<bool>();
    hostTemperatureStop = doc["temperature_stop"].as<bool>();
    alarmAcknowledged = doc["alarm_acknowledged"].as<bool>();
    const char* mode = doc["vent_mode"] | "AUTO";
    ventMode = settingsLocked ? "AUTO" : strcmp(mode, "OPEN") == 0 ? "OPEN" : strcmp(mode, "CLOSED") == 0 ? "CLOSED" : "AUTO";
  }
  bool allowedRun = BENCH_MODE ? runLimit.allow(requestedRun, now) : requestedRun;
  if (!sensorOk || !hardwareReady()) fault(!sensorOk ? "SENSOR_ERROR" : "HARDWARE_NOT_READY");
  else if (localDanger && !(VENTILATION_MODE && isFault)) applyOutputs(VENTILATION_MODE ? "WARNING" : "DANGER", "OPEN", true, VENTILATION_MODE && requestedRun);
  else {
    applyOutputs(state, vent, doc["buzzer"].as<bool>() || danger || isFault, allowedRun);
    if (BENCH_MODE && requestedRun && !allowedRun) faultReason = "BENCH_LIMIT";
  }
  emitAck(seq, session, true);
}

void pollSerial(uint32_t now) {
  // Bound work per iteration so noisy serial traffic cannot starve the watchdog.
  uint8_t budget = 64;
  while (Serial.available() && budget--) {
    char c = Serial.read();
    if (c == '\n') {
      if (!droppingLine && lineLength) {
        lineBuffer[lineLength] = '\0';
        processLine(now);
      }
      lineLength = 0;
      droppingLine = false;
    } else if (!droppingLine) {
      if (lineLength < sizeof(lineBuffer) - 1) lineBuffer[lineLength++] = c;
      else { droppingLine = true; lineLength = 0; fault("LINE_OVERFLOW"); }
    }
  }
}

void lcdLine(uint8_t row, const char* text) {
  lcd.setCursor(0, row);
  lcd.print(text);
  for (uint8_t i = strlen(text); i < LCD_COLUMNS; ++i) lcd.print(' ');
}

void updateLcd(uint32_t now) {
  if (!lcdReady || now - lcdAt < 1000) return;
  lcdAt = now;
  char text[21];
  if (isfinite(temperature) && isfinite(humidity))
    snprintf(text, sizeof(text), "T:%2dC RH:%2d%%", (int)temperature, (int)humidity);
  else snprintf(text, sizeof(text), "DHT11: READ ERROR");
  lcdLine(0, text);
  if (VENTILATION_MODE) snprintf(text, sizeof(text), "MQ9:%4d TRIP:%d", gasRaw, FAN_GAS_TRIP_RAW);
  else if (BENCH_MODE) snprintf(text, sizeof(text), "MQ9:%4d RAW ONLY", gasRaw);
  else snprintf(text, sizeof(text), "MQ9:%4d IR:%s", gasRaw,
      ENABLE_IR ? (digitalRead(IR_PIN) == (IR_ACTIVE_LOW ? LOW : HIGH) ? "YES" : "NO") : "OFF");
  lcdLine(1, text);
  if (VENTILATION_MODE) snprintf(text, sizeof(text), "%s", ventilationStatus(currentState, accessAlert, emergencyStopped, localTempDanger, temperatureStop.active || hostTemperatureStop));
  else snprintf(text, sizeof(text), "%s %s", currentState, deviceEnabled ? "RUN" : "LOCK");
  lcdLine(2, text);
  if (VENTILATION_MODE && !faultReason[0])
    snprintf(text, sizeof(text), "FAN:%s D9:%s", currentFan, strcmp(currentVent, "OPEN") == 0 ? "90" : strcmp(currentVent, "CLOSED") == 0 ? "0" : "HOLD");
  else snprintf(text, sizeof(text), "%s", faultReason[0] ? faultReason : BENCH_MODE ? "BENCH / MAX 10s" : currentVent);
  lcdLine(3, text);
}

void setup() {
  MCUSR = 0;
  wdt_disable();
  Serial.begin(115200);
  if (ENABLE_DHT) dht.begin();
  if (ENABLE_IR) pinMode(IR_PIN, INPUT_PULLUP);
  if (WIRING_CONFIRMED) {
    if (ENABLE_DEVICE_OUTPUT) { digitalWrite(DEVICE_ENABLE_PIN, DEVICE_OFF_LEVEL); pinMode(DEVICE_ENABLE_PIN, OUTPUT); }
    if (ENABLE_STATUS_LEDS) {
      const uint8_t pins[] = {GREEN_LED_PIN, BLUE_LED_PIN, RED_LED_PIN};
      for (uint8_t pin : pins) {
        digitalWrite(pin, activeOutput(false, !RGB_COMMON_ANODE));
        pinMode(pin, OUTPUT);
      }
    }
    if (ENABLE_BUZZER && BUZZER_DRIVE_CONFIRMED) {
      digitalWrite(BUZZER_PIN, BUZZER_ACTIVE ? activeOutput(false, BUZZER_ACTIVE_LEVEL == HIGH) : LOW);
      pinMode(BUZZER_PIN, OUTPUT);
    }
    if (ENABLE_SERVO && (BENCH_MODE || VENTILATION_MODE || VENT_CALIBRATED)) {
      ventServo.write(VENT_CLOSED_ANGLE); ventServo.attach(SERVO_PIN);
    }
    if (ENABLE_ROTATION_SERVO && ROTATION_CALIBRATED) {
      rotationServo.writeMicroseconds(ROTATION_STOP_US);
      rotationServo.attach(ROTATION_SERVO_PIN);
    }
    if (ENABLE_LCD) {
      Wire.begin();
      Wire.setWireTimeout(25000, true);
      for (uint8_t attempt = 0; attempt < 3 && !lcdReady; ++attempt) {
        delay(100); Wire.clearWireTimeoutFlag();
        Wire.beginTransmission(LCD_ADDRESS);
        lcdReady = Wire.endTransmission() == 0 && !Wire.getWireTimeoutFlag();
      }
      if (lcdReady) { lcd.init(); lcd.backlight(); }
    }
  }
  fault("STARTUP");
  if (WIRING_CONFIRMED && VENTILATION_MODE) initVentilationIndicators();
  // AVR watchdog resets a stalled loop. Host timeout below keeps device OFF.
  wdt_enable(WDTO_4S);
}

void loop() {
  wdt_reset();
  uint32_t now = millis();
  pollSerial(now);
  if (!haveCommand || now - commandAt >= HOST_TIMEOUT_MS) fault("COMM_ERROR");
  if (WIRING_CONFIRMED && VENTILATION_MODE) updateVentilationIndicators(currentState, accessAlert, now, emergencyStopped, alarmAcknowledged, localTempDanger, temperatureStop.active || hostTemperatureStop);
  if (BENCH_MODE && deviceEnabled && runLimit.expired(now)) {
    runLimit.trip(); deviceOff(); faultReason = "BENCH_LIMIT";
  }
  // DHT masks interrupts and LCD writes can fill the UART's 64-byte RX buffer.
  // Finish both BEFORE telemetry, leaving the reply slot free for host commands.
  // the host sends at most one command in response to each telemetry packet.
  if (now - telemetryAt >= 500) {
    if (now - sampleAt >= SENSOR_INTERVAL_MS) { sampleAt = now; readSensors(now); }
    updateLcd(now);
    if (ENABLE_LCD && Wire.getWireTimeoutFlag()) {
      Wire.clearWireTimeoutFlag(); lcdReady = false; fault("LCD_I2C_ERROR");
    }
    telemetryAt = millis(); emitTelemetry(telemetryAt);
  }
}
