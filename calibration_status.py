"""Calibration preflight without importing Windows, screen capture, or OCR."""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

CALIBRATION_FILE = Path('configs/ocr_calibration.json')
CALIBRATION_HELP = ('Open the desktop app (EDAPGui.py), select the Calibration tab, calibrate '
                    'Screen_Regions.full_panel and EDCodex.full_panel, then click Save All Calibrations. '
                    'Close the desktop app and restart the Python backend to load the saved regions.')

FSD_REGIONS = {'Screen_Regions.compass', 'Screen_Regions.target', 'Screen_Regions.sun'}
SC_REGIONS = FSD_REGIONS | {'Screen_Regions.disengage', 'Screen_Regions.sco'}
MAP_REGIONS = {'EDGalaxyMap.full_panel', 'EDGalaxyMap.cartographics'}
ASSIST_REGIONS = {
    'fsd': FSD_REGIONS,
    'sc': SC_REGIONS,
    'waypoint': SC_REGIONS | MAP_REGIONS,
    'single_waypoint': SC_REGIONS | MAP_REGIONS,
    'robigo': SC_REGIONS | MAP_REGIONS | {'Screen_Regions.missions', 'Screen_Regions.nav_panel'},
}


def valid_rect(rect):
    """Normalized screen bounds must be finite, ordered, and have positive area."""
    return (isinstance(rect, (list, tuple)) and len(rect) == 4
            and all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in rect)
            and 0 <= rect[0] < rect[2] <= 1 and 0 <= rect[1] < rect[3] <= 1)


def region_problem(data, name):
    # Match load_calibrated_regions: a direct child overrides a cropped subregion.
    if name in data:
        value = data[name]
        return None if isinstance(value, dict) and valid_rect(value.get('rect')) else 'invalid or empty bounds'
    prefix, region = name.split('.', 1)
    parent = f'{prefix}.full_panel'
    child = f'{parent}.subregion.{region}'
    if region != 'full_panel' and parent in data and child in data:
        if region_problem(data, parent):
            return f'parent {parent} has invalid or empty bounds'
        value = data[child]
        return None if isinstance(value, dict) and valid_rect(value.get('rect')) else f'{child} has invalid or empty bounds'
    # nav_panel has a usable built-in rectangle and is not in the calibration UI.
    if name == 'Screen_Regions.nav_panel':
        return None
    return 'missing region'


@dataclass
class CalibrationCheck:
    state: str
    message: str
    issues: list[str]
    blocked_assists: list[str]
    fingerprint: str | None


def inspect_calibration(filename=CALIBRATION_FILE, *, elw_scanner=False):
    required = {mode: set(regions) for mode, regions in ASSIST_REGIONS.items()}
    if elw_scanner:
        for mode in ('fsd', 'waypoint', 'single_waypoint', 'robigo'):
            required[mode] |= {'Screen_Regions.fss', 'EDFSS.full_panel', 'EDFSS.analysis'}
    blocked = sorted(required)
    fingerprint = None
    try:
        with Path(filename).open('rb') as stream:
            contents = stream.read(1024 * 1024 + 1)
        fingerprint = hashlib.sha256(contents).hexdigest()
        if len(contents) > 1024 * 1024:
            raise ValueError('file exceeds 1 MiB')
        data = json.loads(contents.decode('utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('expected an object')
    except FileNotFoundError:
        return CalibrationCheck('missing', 'Screen calibration is missing.',
                                [f'{filename} does not exist.'], blocked, None)
    except (OSError, UnicodeError, ValueError):
        return CalibrationCheck('invalid', 'The screen calibration file is unreadable or invalid.',
                                [f'{filename} must be a readable JSON object, at most 1 MiB.'], blocked, fingerprint)

    problems = {name: problem for name in sorted(set().union(*required.values()))
                if (problem := region_problem(data, name))}
    blocked = sorted(mode for mode, regions in required.items() if regions.intersection(problems))
    issues = [f'{name}: {problem}.' for name, problem in problems.items()]
    message = f'Screen calibration is incomplete. {issues[0]}' if issues else 'Required screen regions are configured.'
    return CalibrationCheck('incomplete' if issues else 'ready', message, issues, blocked, fingerprint)
