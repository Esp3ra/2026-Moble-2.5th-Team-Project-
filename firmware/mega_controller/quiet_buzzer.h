#pragma once
#include <Arduino.h>
#include <avr/interrupt.h>
#include <util/atomic.h>
#include "buzzer_wave.h"

#if MOBLE_VENTILATION_PROFILE
// D28 has no hardware PWM. Timer3 CTC provides variable-width pulses on the
// existing signal pin. Compare C starts a period; compare B ends its HIGH.
// Compare A is deliberately not enabled: Servo defines that ISR even when
// these two servos only use Timer5. Timer1 remains reserved for RGB mixing.
static volatile uint8_t* buzzerOutputPort = nullptr;
static uint8_t buzzerOutputMask = 0;

ISR(TIMER3_COMPC_vect) { *buzzerOutputPort |= buzzerOutputMask; }
ISR(TIMER3_COMPB_vect) { *buzzerOutputPort &= ~buzzerOutputMask; }

inline void setVentilationTone(uint16_t hz) {
  static uint16_t previousHz = 0xffff;
  if (hz == previousHz) return;
  previousHz = hz;
  BuzzerWave wave = planBuzzerWave(hz, BUZZER_DUTY_PERCENT, F_CPU);
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
    TIMSK3 = 0;
    TCCR3B = 0;
    TCCR3A = 0;
    buzzerOutputPort = portOutputRegister(digitalPinToPort(BUZZER_PIN));
    buzzerOutputMask = digitalPinToBitMask(BUZZER_PIN);
    *buzzerOutputPort &= ~buzzerOutputMask;
    TCNT3 = 0;
    TIFR3 = _BV(OCF3A) | _BV(OCF3B) | _BV(OCF3C) | _BV(TOV3);
    if (wave.periodTicks) {
      OCR3A = wave.periodTicks - 1;
      OCR3C = OCR3A;
      OCR3B = wave.highTicks - 1;
      *buzzerOutputPort |= buzzerOutputMask;
      TIMSK3 = _BV(OCIE3B) | _BV(OCIE3C);
      TCCR3B = _BV(WGM32) | _BV(CS31);  // CTC, 16MHz/8 = 2MHz.
    }
  }
}
#endif
