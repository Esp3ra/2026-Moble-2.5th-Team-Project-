"""Bounded JSON Lines framing; a partial/invalid line never refreshes health."""
import json
import math

STATES = ('NORMAL', 'WARNING', 'DANGER', 'FAULT')
MAX_LINE = 1024


class Framer:
    def __init__(self):
        self.buffer = bytearray()
        self.dropping = False
        self.errors = 0

    def feed(self, data):
        packets = []
        for byte in data:
            if byte == 10:
                if not self.dropping and self.buffer:
                    try:
                        obj = json.loads(self.buffer.decode('utf-8'))
                        if not isinstance(obj, dict):
                            raise ValueError('Not an object')
                        packets.append(obj)
                    except (ValueError, UnicodeError):
                        self.errors += 1
                self.buffer.clear()
                self.dropping = False
            elif not self.dropping:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_LINE:
                    self.buffer.clear()
                    self.dropping = True
                    self.errors += 1
        return packets


def finite(value, low, high):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and low <= value <= high)


def telemetry_valid(obj):
    if type(obj.get('v')) is not int or obj['v'] != 1 or obj.get('type') != 'telemetry':
        return False
    for key, low, high in [('temperature', 0, 50), ('humidity', 0, 100), ('gas_raw', 0, 1023)]:
        value = obj.get(key)
        if key not in obj or (value is not None and not finite(value, low, high)):
            return False
    if not isinstance(obj.get('seq'), int) or isinstance(obj['seq'], bool) or not 0 <= obj['seq'] <= 4294967295:
        return False
    if obj.get('ir_detected') is not None and not isinstance(obj['ir_detected'], bool):
        return False
    return isinstance(obj.get('sensor_ok'), bool) and isinstance(obj.get('hardware_ready'), bool)


def command(seq, state, vent, buzzer, device_enable=False, session=1, fan=None, settings_locked=False, access_alert=False,
            vent_mode='AUTO', emergency_stop=False, alarm_acknowledged=False, temperature_stop=False):
    if state not in STATES or vent not in ('CLOSED', 'PARTIAL', 'OPEN', 'SAFE') or not isinstance(buzzer, bool):
        raise ValueError('Invalid control command')
    if not isinstance(device_enable, bool):
        raise ValueError('device_enable must be boolean')
    obj = {'v': 1, 'type': 'command', 'seq': seq, 'session': session, 'state': state, 'vent': vent, 'buzzer': buzzer, 'device_enable': device_enable}
    if fan is not None:
        if (fan not in ('OFF', 'LOW', 'HIGH') or (fan != 'OFF') != device_enable
                or not isinstance(settings_locked, bool) or not isinstance(access_alert, bool)):
            raise ValueError('Invalid fan command')
        obj.update(profile='ventilation', fan=fan, settings_locked=settings_locked, access_alert=access_alert)
        if vent_mode not in ('AUTO', 'OPEN', 'CLOSED') or not isinstance(emergency_stop, bool) or not isinstance(alarm_acknowledged, bool):
            raise ValueError('Invalid ventilation override')
        if emergency_stop and (device_enable or vent != 'CLOSED'):
            raise ValueError('Emergency stop must close the inlet and stop the fan')
        obj.update(vent_mode=vent_mode, emergency_stop=emergency_stop, alarm_acknowledged=alarm_acknowledged)
        if not isinstance(temperature_stop, bool) or (temperature_stop and (device_enable or vent != 'CLOSED')):
            raise ValueError('Temperature stop must close the inlet and stop the fan')
        obj['temperature_stop'] = temperature_stop
    return obj


def ack_matches(ack, expected):
    """Accept a matching response or an explicit MCU safety stop, never an extra RUN."""
    if (ack.get('v') != 1 or ack.get('type') != 'ack' or ack.get('accepted') is not True
            or ack.get('seq') != expected['seq'] or ack.get('session') != expected['session']
            or ack.get('state') not in STATES or ack.get('vent') not in ('CLOSED', 'PARTIAL', 'OPEN', 'SAFE')
            or not isinstance(ack.get('device_enable'), bool)):
        return False
    if 'fan' in expected:
        if (ack.get('profile') != 'ventilation' or ack.get('fan') not in ('OFF', 'LOW', 'HIGH')
                or (ack['fan'] != 'OFF') != ack['device_enable']
                or (ack['device_enable'] and not expected['device_enable'])):
            return False
        if 'temperature_stop' in ack:
            if not isinstance(ack['temperature_stop'], bool):
                return False
            if ack['temperature_stop'] and (ack['device_enable'] or ack['fan'] != 'OFF' or ack['vent'] != 'CLOSED'):
                return False
        if expected.get('temperature_stop') and ack.get('temperature_stop') is not True:
            return False
        if ack['state'] != 'FAULT' and any(ack.get(k) != expected[k] for k in ('access_alert', 'settings_locked')):
            return False
        if (not isinstance(ack.get('emergency_stop'), bool)
                or not isinstance(ack.get('alarm_acknowledged'), bool)
                or ack.get('vent_mode') not in ('AUTO', 'OPEN', 'CLOSED')):
            return False
        if ack['state'] != 'FAULT' and (ack['emergency_stop'] != expected['emergency_stop']
                or ack['vent_mode'] != expected['vent_mode']):
            return False
        if ack['alarm_acknowledged'] and not expected['alarm_acknowledged']:
            return False
        if expected.get('emergency_stop') and (ack.get('vent') != 'CLOSED' or ack.get('device_enable') is not False
                                                or ack.get('emergency_stop') is not True):
            return False
        # A local MCU sensor alert may boost an already permitted fan.
        local_vent = expected['vent_mode'] if expected['vent_mode'] != 'AUTO' else 'OPEN'
        if (expected['device_enable'] and ack['device_enable'] and ack['state'] == 'WARNING'
                and ack['vent'] == local_vent and ack['fan'] == 'HIGH' and ack.get('environment_alert') is True):
            return True
    exact = all(ack.get(k) == expected[k] for k in ('state', 'vent', 'device_enable'))
    if 'fan' in expected:
        exact = exact and ack['fan'] == expected['fan']
    stopped = ack['device_enable'] is False and (ack['state'] in ('WARNING', 'DANGER', 'FAULT') or ack.get('fault') == 'BENCH_LIMIT')
    return exact or stopped


def automatic_temperature_stop(ack):
    """Only this explicit, non-fault MCU stop is allowed to resume automatically."""
    return (ack.get('profile') == 'ventilation' and ack.get('temperature_stop') is True
            and ack.get('state') == 'WARNING' and not ack.get('fault')
            and ack.get('device_enable') is False and ack.get('fan') == 'OFF'
            and ack.get('vent') == 'CLOSED' and ack.get('emergency_stop') is False)


def encode(obj):
    return (json.dumps(obj, separators=(',', ':'), allow_nan=False) + '\n').encode('ascii')
