"""Deterministic fusion with hysteresis, faults and delayed recovery."""
from .protocol import finite

TEMPERATURE_RESTART_SECONDS = 5.0


class Controller:
    def __init__(self, cfg, simulation=False):
        self.cfg = cfg
        self.simulation = simulation
        self.temp_level = self.gas_level = 0
        self.state = 'FAULT'
        self.pending = None
        self.pending_since = 0
        self.manual = None
        self.manual_until = 0
        self.temperature_stop = False
        self.temperature_normal_since = None
        self.last_temperature_stop = False

    def update_temperature_stop(self, telemetry, valid, now):
        # A critical reading trips immediately. Only uninterrupted, valid normal
        # readings release the latch; manual STOP is owned separately by Runtime.
        if not valid:
            self.temperature_normal_since = None
            return
        value = telemetry['temperature']
        if value >= self.cfg['thresholds']['temp_danger']:
            self.temperature_stop = True
        if self.temperature_stop and value < self.cfg['thresholds']['temp_warning']:
            if self.temperature_normal_since is None:
                self.temperature_normal_since = now
            elif now - self.temperature_normal_since >= TEMPERATURE_RESTART_SECONDS:
                self.temperature_stop = False
                self.temperature_normal_since = None
        else:
            self.temperature_normal_since = None

    def manual_vent(self, target, now):
        if target not in ('CLOSED', 'PARTIAL', 'OPEN', None):
            raise ValueError('Invalid manual vent target')
        self.manual = target
        self.manual_until = now + self.cfg['control']['manual_seconds']

    def level(self, value, previous, prefix):
        t = self.cfg['thresholds']
        warn, danger, hyst = (t[prefix + '_' + k] for k in ('warning', 'danger', 'hysteresis'))
        if value >= danger or (previous == 2 and value >= danger - hyst):
            return 2
        if value >= warn or (previous >= 1 and value >= warn - hyst):
            return 1
        return 0

    def evaluate(self, telemetry, sensor_at, vision, camera_at, now, comm_ok=True, extra_faults=()):
        faults = list(extra_faults)
        reasons = []
        bench = not self.simulation and self.cfg['hardware']['profile'] == 'bench'
        ventilation = self.cfg['hardware']['profile'] == 'ventilation'
        temperature_released = False
        if not comm_ok or telemetry is None or now - sensor_at > self.cfg['serial']['stale_seconds']:
            faults.append('COMM_ERROR')
        if camera_at is None or now - camera_at > self.cfg['camera']['stale_seconds']:
            faults.append('CAMERA_ERROR')
        elif vision not in ('GREEN', 'RED', 'CLEAR', 'AUTHORIZED', 'UNAUTHORIZED') and not (ventilation and vision == 'CLEARING'):
            faults.append('VISION_UNKNOWN')
        if not self.simulation and not (self.cfg['hardware']['confirmed'] and (bench or ventilation or self.cfg['hardware']['gas_calibrated'])):
            faults.append('CONFIG_REQUIRED')
        if telemetry is not None:
            valid = (telemetry.get('sensor_ok') is True
                     and finite(telemetry.get('temperature'), 0, 50)
                     and finite(telemetry.get('humidity'), 0, 100)
                     and finite(telemetry.get('gas_raw'), 0, 1023))
            if not valid:
                faults.append('SENSOR_ERROR')
            else:
                previous_temp_level = self.temp_level
                self.temp_level = self.level(telemetry['temperature'], self.temp_level, 'temp')
                temperature_released = previous_temp_level > 0 and self.temp_level == 0
                self.gas_level = 0 if bench else self.level(telemetry['gas_raw'], self.gas_level, 'gas')
                if self.temp_level:
                    reasons.append('HIGH_TEMPERATURE')
                if self.gas_level:
                    reasons.append('GAS_RESPONSE')
            if not self.simulation and telemetry.get('hardware_ready') is not True:
                faults.append('HARDWARE_NOT_READY')
            if not self.simulation:
                expected = self.cfg['hardware']['profile']
                if telemetry.get('profile', 'production') != expected:
                    faults.append('FIRMWARE_PROFILE_MISMATCH')
                if bench and (telemetry.get('gas_guard') is not False or telemetry.get('bench_run_ms') != 10000):
                    faults.append('BENCH_LIMIT_NOT_CONFIRMED')
                if ventilation:
                    limits = self.cfg['thresholds']
                    expected_values = {'policy_rev': 6, 'gas_mode': 'raw_demo', 'bench_run_ms': 0,
                                       'temp_restart_ms': int(TEMPERATURE_RESTART_SECONDS * 1000),
                                       'temp_trip': limits['temp_warning'], 'gas_trip': limits['gas_warning'],
                                       'temp_red': limits['temp_danger'],
                                       'temp_release': limits['temp_warning'] - limits['temp_hysteresis'],
                                       'gas_release': limits['gas_warning'] - limits['gas_hysteresis']}
                    if any(telemetry.get(k) != value for k, value in expected_values.items()):
                        faults.append('VENTILATION_POLICY_MISMATCH')
                    if any(not isinstance(telemetry.get(k), bool) for k in ('temperature_stop', 'local_temperature_stop')):
                        faults.append('VENTILATION_POLICY_MISMATCH')
                mcu_fault = telemetry.get('fault', '')
                if mcu_fault and mcu_fault != 'BENCH_LIMIT':
                    faults.append('MCU_' + str(mcu_fault))
            if self.cfg['hardware']['require_ir'] and telemetry.get('ir_detected') is None:
                faults.append('IR_ERROR')
            if telemetry.get('ir_detected') is True:
                reasons.append('IR_DETECTED')
        if vision == 'RED':
            reasons.append('VISUAL_ABNORMAL')
        if vision == 'UNAUTHORIZED':
            reasons.append('UNAUTHORIZED_PERSON')
        if ventilation:
            self.update_temperature_stop(telemetry, telemetry is not None and not faults, now)
            # The Mega can detect a trip before the host receives that sample.
            # Keep the host's release timer independent to avoid feedback latching.
            thermal_stop = self.temperature_stop or bool(telemetry and telemetry.get('local_temperature_stop') is True)
            temperature_released = temperature_released or (self.last_temperature_stop and not thermal_stop)
            self.last_temperature_stop = thermal_stop
            if thermal_stop:
                reasons.append('TEMPERATURE_AUTO_STOP')
                if self.temp_level == 0:
                    reasons.append('TEMPERATURE_COOLING_WAIT')
            return self.ventilation_decision(faults, reasons, vision, now, temperature_released, thermal_stop)
        severity = max(self.temp_level, self.gas_level,
                       1 if vision == 'RED' or 'IR_DETECTED' in reasons else 0)
        if vision == 'RED' and (self.temp_level > 0 or self.gas_level > 0):
            severity = 2
        if vision == 'UNAUTHORIZED':
            severity = 2
        # Preserve known danger as a reason even if an independent device fails.
        if severity == 2:
            reasons.append('DANGER_CONDITION')
        target = 'FAULT' if faults else ('NORMAL', 'WARNING', 'DANGER')[severity]
        rank = {'NORMAL': 0, 'WARNING': 1, 'DANGER': 2, 'FAULT': 3}
        if rank[target] >= rank[self.state]:
            self.state, self.pending = target, None
        elif self.pending != target:
            self.pending, self.pending_since = target, now
        elif now - self.pending_since >= self.cfg['control']['recovery_seconds']:
            self.state, self.pending = target, None
        if self.pending:
            reasons.append('RECOVERY_WAIT')
        vent = {'NORMAL': 'CLOSED', 'WARNING': 'PARTIAL', 'DANGER': 'OPEN', 'FAULT': 'SAFE'}[self.state]
        if self.state == 'FAULT' and severity == 2:
            vent = 'OPEN'
        if self.manual and now >= self.manual_until:
            self.manual = None
        # Manual control can only open further; it never suppresses an alarm.
        if self.manual and self.state != 'FAULT':
            positions = ('CLOSED', 'PARTIAL', 'OPEN')
            vent = positions[max(positions.index(vent), positions.index(self.manual))]
        return {'state': self.state, 'vent': vent, 'buzzer': self.state in ('DANGER', 'FAULT'),
                'faults': sorted(set(faults)), 'reasons': reasons,
                'mode': 'MANUAL' if self.manual else 'AUTO', 'target': target}

    def ventilation_decision(self, faults, reasons, vision, now, temperature_released=False, thermal_stop=False):
        # Access permission is independent of the displayed alarm priority.
        environment = max(self.temp_level, self.gas_level) > 0 or thermal_stop
        intrusion = vision == 'UNAUTHORIZED'
        locked = vision not in ('CLEAR', 'AUTHORIZED') or bool(faults)
        target = 'FAULT' if faults else 'WARNING' if environment else 'DANGER' if intrusion else 'NORMAL'
        # Environmental WARNING (orange) outranks intrusion DANGER (red).
        rank = {'NORMAL': 0, 'DANGER': 1, 'WARNING': 2, 'FAULT': 3}
        if rank[target] >= rank[self.state] or (self.state == 'WARNING' and temperature_released and not environment):
            self.state, self.pending = target, None
        elif self.pending != target:
            self.pending, self.pending_since = target, now
        elif now - self.pending_since >= self.cfg['control']['recovery_seconds']:
            self.state, self.pending = target, None
        if self.pending:
            reasons.append('RECOVERY_WAIT')
        if locked:
            self.manual = None
        vent = 'SAFE' if self.state == 'FAULT' else 'OPEN' if self.state == 'WARNING' else 'CLOSED'
        if self.state == 'FAULT' and environment:
            vent = 'OPEN'
        if self.manual and not locked:
            vent = self.manual
        if thermal_stop:
            vent = 'CLOSED'
        return {'state': self.state, 'target': target, 'vent': vent,
                'buzzer': self.state in ('WARNING', 'FAULT') and not thermal_stop, 'environment_alert': environment,
                'temperature_danger': self.temp_level == 2,
                'temperature_stop': thermal_stop,
                'access_alert': intrusion, 'settings_locked': locked,
                'fan': 'OFF' if self.state == 'FAULT' or thermal_stop else 'HIGH' if self.state == 'WARNING' else 'LOW',
                'faults': sorted(set(faults)), 'reasons': reasons,
                'mode': 'MANUAL' if self.manual else 'AUTO'}
