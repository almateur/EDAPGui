"""Build-specific tuning profiles and atomic persistence, independent of Windows."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

MODES = ('Speed0', 'Speed50', 'Speed100', 'SCSpeed0', 'SCSpeed50', 'SCSpeed100')
AXES = ('RollRate', 'PitchRate', 'YawRate')
FALLBACK = {'RollRate': 80.0, 'PitchRate': 33.0, 'YawRate': 8.0, 'SunPitchUp+Time': 0.0}


def now():
    return datetime.now(timezone.utc).isoformat()


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 < value <= 10000


def atomic_json(filename, value):
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=filename.name + '.', suffix='.tmp', dir=filename.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, filename)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ShipProfiles:
    def __init__(self, defaults, filename='configs/ship_configs.json'):
        self.lock = threading.RLock()
        self.defaults, self.filename = defaults, Path(filename)
        try:
            with self.filename.open(encoding='utf-8-sig') as stream:
                self.data = json.load(stream)
        except FileNotFoundError:
            self.data = {'Ship_Configs': {}}
        if not isinstance(self.data, dict):
            raise ValueError('Ship configuration must be a JSON object; back up and repair configs/ship_configs.json.')
        for name in ('Ship_Configs', 'Build_Profiles'):
            if name not in self.data:
                self.data[name] = {}
            if not isinstance(self.data[name], dict):
                raise ValueError(f'Ship configuration {name} must be an object.')
        self.profile = None
        self.key = None
        self.token = None
        self.dirty = False
        self.last_save = 0.0
        self.save_error = None

    def select(self, summary):
        with self.lock:
            key, ship = summary.get('profile_key'), summary.get('ship_type')
            token = key or ('pending', summary.get('identity'), ship, summary.get('build_signature'), summary.get('stale'))
            if token == self.token:
                self.save()
                return False
            self.save(force=True)
            profiles = self.data['Build_Profiles']
            profile = profiles.get(key) if key else None
            if profile is not None and not isinstance(profile, dict):
                raise ValueError('The saved build profile is invalid.')
            if profile is not None:
                meta = profile.get('_Meta', {})
                if (not isinstance(meta, dict) or meta.get('identity') != summary.get('identity')
                        or meta.get('build_signature') != summary.get('build_signature')):
                    raise ValueError('Saved profile identity does not match the current ship and build.')
            if profile is None:
                rates = dict(FALLBACK)
                rates.update(self.defaults.get(ship, {}))
                # Existing type-wide values remain a visible, unverified migration
                # seed. A changed build never silently inherits the old build's curves.
                previous_build = any(isinstance(p, dict) and p.get('_Meta', {}).get('identity') == summary.get('identity')
                                     for p in profiles.values()) if summary.get('identity') else False
                legacy = self.data['Ship_Configs'].get(ship, {}) if key and not previous_build else {}
                legacy = legacy if isinstance(legacy, dict) else {}
                profile = deepcopy(legacy)
                for axis in AXES:
                    profile[axis] = legacy[axis] if positive(legacy.get(axis)) else rates[axis]
                extra = legacy.get('SunPitchUp+Time', rates.get('SunPitchUp+Time', 0.0))
                profile['SunPitchUp+Time'] = extra if isinstance(extra, (int, float)) and math.isfinite(extra) else 0.0
                profile['_Meta'] = {'identity': summary.get('identity'), 'ship_type': ship,
                                    'ship_id': summary.get('ship_id'), 'build_signature': summary.get('build_signature'),
                                    'seed_source': 'legacy_unverified' if legacy else 'ship_defaults' if ship in self.defaults else 'generic_defaults',
                                    'created_at': now(), 'measured': {}}
                if key:
                    profiles[key] = profile
            self._normalize(profile)
            self.profile, self.key, self.token = profile, key, token
            self.dirty = self.dirty or bool(key)
            self.save(force=True)
            return True

    @staticmethod
    def _normalize(profile):
        for axis in AXES:
            if not positive(profile.get(axis)):
                raise ValueError(f'Saved ship {axis} must be a positive, finite rate.')
        for mode in MODES:
            if not isinstance(profile.get(mode), dict):
                profile[mode] = {}
            for axis in AXES:
                curve = profile[mode].get(axis)
                if isinstance(curve, dict) and curve:
                    try:
                        if not all(math.isfinite(float(angle)) and float(angle) >= 0 and positive(rate) for angle, rate in curve.items()):
                            raise ValueError('Invalid curve')
                        normalized = {str(float(angle)): rate for angle, rate in curve.items()}
                        if len(normalized) != len(curve):
                            raise ValueError('Duplicate tuning angles')
                        curve = dict(sorted(normalized.items(), key=lambda item: float(item[0])))
                    except (ValueError, TypeError):
                        raise ValueError(f'Invalid {mode} {axis} tuning curve; repair the saved profile.')
                else:
                    angles = (5.0, 45.0, 60.0) if axis == 'RollRate' else (.5, 30.0, 60.0)
                    rate = profile[axis]
                    curve = {str(angle): rate / 2 if i == 0 else rate for i, angle in enumerate(angles)}
                profile[mode][axis] = curve
        if not isinstance(profile.get('_Meta'), dict):
            raise ValueError('Saved build profile metadata is invalid.')
        profile['_Meta'].setdefault('measured', {})
        if not isinstance(profile['_Meta']['measured'], dict):
            raise ValueError('Saved measurement metadata must be an object.')
        for axes in profile['_Meta']['measured'].values():
            if not isinstance(axes, dict) or any(not isinstance(points, dict) for points in axes.values()):
                raise ValueError('Saved measurement points must be objects.')
            for points in axes.values():
                if any(not isinstance(point, dict) or not isinstance(point.get('samples', 0), int) for point in points.values()):
                    raise ValueError('Saved measurement samples are invalid.')

    def record(self, mode, axis, angle, rate, context=None):
        with self.lock:
            if not self.key or not self.profile or mode not in MODES or axis not in AXES or not positive(rate):
                return False
            if not isinstance(angle, (float, int)) or not math.isfinite(angle) or angle < 0:
                return False
            points = self.profile['_Meta']['measured'].setdefault(mode, {}).setdefault(axis, {})
            name = str(float(angle))
            curve = {**self.profile[mode][axis], name: rate}
            self.profile[mode][axis] = dict(sorted(curve.items(), key=lambda item: float(item[0])))
            count = points.get(name, {}).get('samples', 0) + 1
            points[name] = {'rate': rate, 'samples': count, 'updated_at': now(), 'context': deepcopy(context)}
            self.dirty = True
            self.save()
            return True

    def save(self, force=False):
        with self.lock:
            if not self.dirty or (not force and time.monotonic() - self.last_save < 5):
                return False
            profiles = self.data['Build_Profiles']
            stamps = {key: profile['_Meta'].get('saved_at') for key, profile in profiles.items() if isinstance(profile, dict) and isinstance(profile.get('_Meta'), dict)}
            stamp = now()
            for key in stamps:
                profiles[key]['_Meta']['saved_at'] = stamp
            self.last_save = time.monotonic()
            try:
                atomic_json(self.filename, self.data)
            except (OSError, ValueError, TypeError) as error:
                for key, value in stamps.items():
                    profiles[key]['_Meta']['saved_at'] = value
                self.save_error = str(error)
                return False
            self.dirty = False
            self.last_save = time.monotonic()
            self.save_error = None
            return True

    def describe(self):
        with self.lock:
            meta = deepcopy(self.profile.get('_Meta', {})) if self.profile else {}
            measured = meta.get('measured', {})
            return {'key': self.key, 'seed_source': meta.get('seed_source', 'unavailable'),
                    'saved_at': meta.get('saved_at'), 'dirty': self.dirty, 'save_error': self.save_error,
                    'measured': measured, 'measured_points': sum(len(points) for axes in measured.values() for points in axes.values()),
                    'curves': {mode: deepcopy(self.profile[mode]) for mode in MODES} if self.profile else {}}
