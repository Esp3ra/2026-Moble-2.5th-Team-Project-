#pragma once
#ifndef MOBLE_BENCH_PROFILE
#define MOBLE_BENCH_PROFILE 0
#endif
constexpr bool BENCH_MODE = MOBLE_BENCH_PROFILE != 0;
#ifndef MOBLE_VENTILATION_PROFILE
#define MOBLE_VENTILATION_PROFILE 0
#endif
constexpr bool VENTILATION_MODE = MOBLE_VENTILATION_PROFILE != 0;
static_assert(!(BENCH_MODE && VENTILATION_MODE), "Choose one profile");
// Proposed wiring is documented in docs/WIRING.md. Verify printed module labels
// and power ratings before enabling a peripheral or flashing a connected board.
// Defaults intentionally keep all unverified actuators disabled.
#ifndef WIRING_CONFIRMED
#define WIRING_CONFIRMED 0
#endif
#ifndef ENABLE_DHT
#define ENABLE_DHT 1
#endif
#ifndef ENABLE_GAS
#define ENABLE_GAS 0
#endif
#ifndef ENABLE_IR
#define ENABLE_IR 0
#endif
#ifndef ENABLE_LCD
#define ENABLE_LCD 0
#endif
#ifndef ENABLE_SERVO
#define ENABLE_SERVO 0
#endif
#ifndef ENABLE_ROTATION_SERVO
#define ENABLE_ROTATION_SERVO 0
#endif
#ifndef ENABLE_BUZZER
#define ENABLE_BUZZER 0
#endif
#ifndef ENABLE_STATUS_LEDS
#define ENABLE_STATUS_LEDS 0
#endif
#ifndef ENABLE_DEVICE_OUTPUT
#define ENABLE_DEVICE_OUTPUT 0
#endif

constexpr uint8_t DHT_PIN = 2;
constexpr uint8_t GAS_PIN = A0;
constexpr uint8_t IR_PIN = 3;
constexpr bool IR_ACTIVE_LOW = true;  // Confirm your IR module's OUT polarity.
constexpr uint8_t GREEN_LED_PIN = 22;
constexpr uint8_t BLUE_LED_PIN = 24;  // HW-479 RGB: WARNING = red + green.
constexpr uint8_t RED_LED_PIN = 26;
constexpr bool RGB_COMMON_ANODE = false;  // User confirmed common - / GND.
constexpr uint8_t BUZZER_PIN = 28;  // Passive piezo or a properly driven module.
constexpr bool BUZZER_ACTIVE = false;  // User heard 1/2 kHz tone; DC test was silent.
constexpr uint8_t BUZZER_ACTIVE_LEVEL = LOW;  // Only used in active-module mode.
constexpr bool BUZZER_DRIVE_CONFIRMED = true;  // Tone drive verified on this module.
// User found 17% duty still too loud; reduce the pulse duty further to 5%.
// Perceived loudness depends on the module; this is not a calibrated dB value.
constexpr uint8_t BUZZER_DUTY_PERCENT = 5;
static_assert(BUZZER_DUTY_PERCENT > 0 && BUZZER_DUTY_PERCENT <= 50, "Invalid buzzer duty");
constexpr uint8_t SERVO_PIN = 9;
constexpr uint8_t ROTATION_SERVO_PIN = 10;
constexpr uint16_t ROTATION_STOP_US = 1500;  // User confirmed stop in 3 bench cycles.
constexpr uint16_t ROTATION_RUN_US = 1600;   // User confirmed continuous rotation.
constexpr uint16_t FAN_LOW_US = 1600;
constexpr uint16_t FAN_HIGH_US = 1800;       // Compare physical speed during commissioning.
constexpr float FAN_TEMP_TRIP_C = 27.0f;     // User selected 2026-10-15.
constexpr float FAN_TEMP_RELEASE_C = 27.0f;
constexpr float FAN_TEMP_RED_C = 28.0f;
constexpr uint32_t FAN_TEMP_RESTART_MS = 5000;
constexpr int FAN_GAS_TRIP_RAW = 250;        // Demo ADC threshold, NOT ppm.
constexpr int FAN_GAS_RELEASE_RAW = 210;
constexpr bool ROTATION_CALIBRATED = true;  // 2026-10-14, external 5V 2A, no load.
static_assert(ROTATION_STOP_US >= 1000 && ROTATION_STOP_US <= 2000, "Invalid servo neutral");
static_assert(ROTATION_RUN_US >= 1000 && ROTATION_RUN_US <= 2000, "Invalid servo run pulse");
constexpr uint8_t DEVICE_ENABLE_PIN = 30;
constexpr uint8_t DEVICE_ACTIVE_LEVEL = HIGH;  // LED demonstration default.
constexpr uint8_t DEVICE_OFF_LEVEL = LOW;      // Active-low relay needs inversion.
constexpr uint8_t LCD_ADDRESS = 0x27;          // Observed on the connected Mega.
constexpr uint8_t LCD_COLUMNS = 20;
constexpr uint8_t LCD_ROWS = 4;
constexpr bool VENT_CALIBRATED = false;        // Actual linkage not commissioned.
constexpr uint8_t VENT_CLOSED_ANGLE = BENCH_MODE ? 75 : 0;
constexpr uint8_t VENT_PARTIAL_ANGLE = BENCH_MODE ? 90 : 45;
constexpr uint8_t VENT_OPEN_ANGLE = BENCH_MODE ? 105 : 90;
constexpr bool MOVE_VENT_ON_FAULT = false;     // Default: retain last vent angle.
constexpr uint8_t VENT_FAULT_ANGLE = 90;
constexpr bool GAS_MODEL_CONFIRMED = true;   // User identified MQ-9.
// Fixed 5V module readings are raw response only, not calibrated CO/ppm.
// Heater mode, initial conditioning and startup stability must be checked.
constexpr uint32_t GAS_WARMUP_MS = 0;        // Remains blocked until commissioned.
constexpr int GAS_DANGER_RAW = 600;           // Demo value; calibrate first.
constexpr int GAS_RECOVER_RAW = 560;
constexpr float TEMP_DANGER_C = 38.0f;
constexpr float TEMP_RECOVER_C = 36.0f;
constexpr uint32_t HOST_TIMEOUT_MS = 3000;
constexpr uint32_t SENSOR_INTERVAL_MS = 2500;
