#pragma once
#include <Arduino.h>
#include <avr/interrupt.h>
#include "quiet_buzzer.h"

#if MOBLE_VENTILATION_PROFILE
// Two Servo instances use Timer5; the quieter buzzer uses Timer3. Reserve Timer1
// compare B for software PWM on the existing D22 green channel (no rewiring).
// Do not add >12 Servo instances or another Timer1 consumer to this profile.
volatile uint8_t greenMixDuty = 0;
ISR(TIMER1_COMPB_vect) {
  static uint8_t phase = 0;
  phase = (phase + 1) & 7;
  uint8_t duty = greenMixDuty;
  if (duty && (phase == 0 || phase == duty))
    digitalWrite(GREEN_LED_PIN, activeOutput(phase == 0, !RGB_COMMON_ANODE));
}

inline void initVentilationIndicators() {
  if (ENABLE_BUZZER && BUZZER_DRIVE_CONFIRMED) setVentilationTone(0);
  TCCR1A = 0;
  TCCR1B = _BV(WGM12) | _BV(CS11);  // 16MHz/8/(249+1) = 8kHz, 1kHz LED cycle.
  TCNT1 = 0;
  OCR1A = 249;
  OCR1B = 124;
  TIMSK1 = _BV(OCIE1B);
}

inline void updateVentilationIndicators(const char* state, bool accessAlert, uint32_t now,
                                       bool emergencyStop = false, bool acknowledged = false, bool temperatureDanger = false,
                                       bool temperatureStop = false) {
  static uint32_t updated = 0;
  if (now - updated < 20) return;
  updated = now;
  bool environment = strcmp(state, "WARNING") == 0;
  bool intrusion = strcmp(state, "DANGER") == 0;
  bool normal = strcmp(state, "NORMAL") == 0;
  bool fault = !normal && !environment && !intrusion;
  bool redPhase = ventilationRedPhase(state, accessAlert, now, temperatureDanger || temperatureStop);
  bool orangePhase = ventilationOrangePhase(state, accessAlert, now, temperatureDanger || temperatureStop) && !emergencyStop;
  bool green = !environment && !fault && !redPhase && !emergencyStop;
  bool red = !emergencyStop && (environment || redPhase || (fault && now % 600 < 300));
  if (ENABLE_STATUS_LEDS) {
    greenMixDuty = orangePhase ? 2 : 0;  // Red 100% + green 25% = orange mix.
    digitalWrite(RED_LED_PIN, activeOutput(red, !RGB_COMMON_ANODE));
    digitalWrite(BLUE_LED_PIN, activeOutput(false, !RGB_COMMON_ANODE));
    if (!orangePhase) digitalWrite(GREEN_LED_PIN, activeOutput(green, !RGB_COMMON_ANODE));
  }
  uint16_t hz = ventilationBuzzerHz(state, now, emergencyStop || temperatureStop, acknowledged);
  if (ENABLE_BUZZER && BUZZER_DRIVE_CONFIRMED) setVentilationTone(hz);
}
#else
inline void initVentilationIndicators() {}
inline void updateVentilationIndicators(const char*, bool, uint32_t, bool = false, bool = false, bool = false, bool = false) {}
#endif
