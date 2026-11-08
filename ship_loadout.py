"""Lossless ship/loadout extraction and stable identities, without game dependencies."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import threading


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def engineering_identity(value):
    if isinstance(value, list):
        return [engineering_identity(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: engineering_identity(item) for key, item in value.items()
              if key not in {'Engineer', 'EngineerID'} and not key.endswith('_Localised')}
    if isinstance(result.get('Modifiers'), list):
        result['Modifiers'] = sorted(result['Modifiers'], key=lambda item: json.dumps(item, sort_keys=True))
    return result


def build_signature(loadout):
    modules = loadout.get('Modules')
    if not isinstance(modules, list) or not modules:
        return None
    slots, fitted = set(), []
    for module in modules:
        if (not isinstance(module, dict) or not isinstance(module.get('Slot'), str)
                or not isinstance(module.get('Item'), str) or not module['Slot'] or not module['Item']
                or module['Slot'].lower() in slots):
            return None
        slot = module['Slot'].lower()
        slots.add(slot)
        if slot.startswith(('paintjob', 'shipkit', 'decal')):
            continue
        fitted.append({'slot': slot, 'item': module['Item'].lower(),
                       'engineering': engineering_identity(module.get('Engineering'))})
    fitted.sort(key=lambda item: item['slot'])
    return digest({'ship': str(loadout.get('Ship', '')).lower(), 'modules': fitted,
                   'unladen_mass': loadout.get('UnladenMass')})


class ShipLoadout:
    OUTFITTING_EVENTS = {'ModuleBuy', 'ModuleSell', 'ModuleStore', 'ModuleRetrieve', 'ModuleSwap',
                         'MassModuleStore', 'EngineerCraft', 'EngineerLegacyConvert'}

    def __init__(self):
        self.lock = threading.RLock()
        self.account = None
        self.ship_type = None
        self.ship_id = None
        self.name = ''
        self.ident = ''
        self.loadout = None
        self.signature = None
        self.stale = True
        self.reason = 'Waiting for a Loadout event from the game journal.'
        self.revision = 0
        self.events = {}

    def consume(self, event):
        if not isinstance(event, dict):
            return False
        kind = event.get('event')
        with self.lock:
            if kind in {'Commander', 'LoadGame'}:
                account = ('fid:' + event['FID']) if isinstance(event.get('FID'), str) and event['FID'] else event.get('Commander') or event.get('Name')
                if isinstance(account, str) and account:
                    # FID is stable across commander renames; never expose it in snapshots.
                    if self.account is not None and kind == 'LoadGame' and account != self.account:
                        self.loadout, self.signature = None, None
                        self.ship_type, self.ship_id = None, None
                        self.name, self.ident, self.events = '', '', {}
                        self.stale = True
                    if kind == 'LoadGame' or self.account is None:
                        self.account = account
                if kind == 'LoadGame':
                    self._identify(event.get('Ship'), event.get('ShipID'))
                    self.name = event.get('ShipName', self.name)
                    self.ident = event.get('ShipIdent', self.ident)
                self.revision += 1
                return True
            if kind in {'ShipyardSwap', 'ShipyardBuy'}:
                self._identify(event.get('ShipType'), event.get('ShipID'))
                self.revision += 1
                return True
            if kind == 'Loadout':
                if not isinstance(event.get('Ship'), str):
                    return False
                self._identify(event['Ship'], event.get('ShipID'))
                self.name = event.get('ShipName', self.name)
                self.ident = event.get('ShipIdent', self.ident)
                try:
                    json.dumps(event, allow_nan=False)
                    signature = build_signature(event)
                except (TypeError, ValueError):
                    self.stale = True
                    self.reason = 'The loadout contains invalid values. Waiting for a valid Loadout event.'
                    self.revision += 1
                    return True
                self.loadout = deepcopy(event)
                self.signature = signature
                self.stale = signature is None
                self.reason = 'Loadout modules are missing or incomplete.' if self.stale else ''
                self.revision += 1
                return True
            if kind == 'SetUserShipName' and event.get('ShipID', self.ship_id) == self.ship_id:
                self.name = event.get('UserShipName', self.name)
                self.ident = event.get('UserShipId', self.ident)
                self.events[kind] = deepcopy(event)
                self.revision += 1
                return True
            if kind in self.OUTFITTING_EVENTS and event.get('ShipID', self.ship_id) == self.ship_id:
                self.stale = True
                self.reason = 'Outfitting or engineering changed. Waiting for the next complete Loadout event.'
                self.events[kind] = deepcopy(event)
                self.revision += 1
                return True
            if kind in {'Cargo', 'HullDamage', 'RepairAll', 'Repair', 'Resurrect'}:
                if kind == 'Cargo' and event.get('Vessel', 'Ship') != 'Ship':
                    return False
                self.events[kind] = deepcopy(event)
                self.revision += 1
                return True
        return False

    def _identify(self, ship_type, ship_id):
        ship_type = ship_type.lower() if isinstance(ship_type, str) else None
        ship_id = ship_id if isinstance(ship_id, int) and not isinstance(ship_id, bool) and ship_id >= 0 else None
        if (ship_type, ship_id) != (self.ship_type, self.ship_id):
            self.ship_type, self.ship_id = ship_type, ship_id
            self.loadout, self.signature, self.events = None, None, {}
            self.name, self.ident = '', ''
            self.stale = True
            self.reason = 'Ship changed. Waiting for its complete Loadout event.'

    def summary(self):
        with self.lock:
            identity = digest([self.account, self.ship_type, self.ship_id]) if self.account and self.ship_type and self.ship_id is not None else None
            key = digest([identity, self.signature]) if identity and self.signature and not self.stale else None
            return {'ship_type': self.ship_type, 'ship_id': self.ship_id, 'ship_name': self.name,
                    'ship_ident': self.ident, 'identity': identity, 'build_signature': self.signature,
                    'profile_key': key, 'stale': self.stale, 'reason': self.reason,
                    'identity_known': identity is not None, 'revision': self.revision}

    def snapshot(self):
        with self.lock:
            return {**self.summary(), 'loadout': deepcopy(self.loadout), 'events': deepcopy(self.events)}


def read_status_once(filename):
    """One bounded read; a half-written Status.json must not block telemetry."""
    try:
        with Path(filename).open('rb') as stream:
            contents = stream.read(1024 * 1024 + 1)
        if len(contents) > 1024 * 1024:
            return None
        data = json.loads(contents.decode('utf-8-sig'))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, UnicodeError, TypeError):
        return None


def flight_info(data, journal_state=None):
    data = data if isinstance(data, dict) else {}
    flags = data.get('Flags')
    flags = flags if isinstance(flags, int) and not isinstance(flags, bool) else None
    pips = data.get('Pips')
    valid_pips = (isinstance(pips, list) and len(pips) == 3
                  and all(isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p) and 0 <= p <= 8 for p in pips))
    mode = 'supercruise' if flags is not None and flags & 16 else 'normal' if flags is not None else 'unknown'
    if mode == 'unknown' and isinstance(journal_state, dict):
        if journal_state.get('status') == 'in_supercruise':
            mode = 'supercruise'
    return {'mode': mode, 'pips': dict(zip(('system', 'engine', 'weapons'), (p / 2 for p in pips))) if valid_pips else None,
            'cargo': data.get('Cargo'), 'fuel': data.get('Fuel'), 'timestamp': data.get('timestamp'),
            'flight_assist_off': bool(flags & 32) if flags is not None else None,
            'flags': flags, 'flags2': data.get('Flags2')}
