"""Read real journal records through EDJournal with only Windows path lookup stubbed."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def journal_module():
    logger = types.ModuleType('EDlogger')
    logger.logger = Mock()
    windows = types.ModuleType('WindowsKnownPaths')
    spec = importlib.util.spec_from_file_location('_ship_journal_test', ROOT / 'EDJournal.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'EDlogger': logger, 'WindowsKnownPaths': windows}):
        spec.loader.exec_module(module)
    return module


class JournalShipTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filename = Path(self.directory.name) / 'Journal.test.log'
        self.loadout = json.loads((ROOT / 'tests/fixtures/engineered-loadout.json').read_text())
        events = [{'event': 'LoadGame', 'FID': 'FTEST', 'Ship': 'python', 'ShipID': 42}, self.loadout,
                  {'event': 'FuelScoop', 'FuelLevel': 0, 'Total': 0}]
        self.filename.write_text(''.join(json.dumps(event) + '\n' for event in events))
        module = journal_module()
        with patch.object(module.EDJournal, 'get_latest_log', return_value=str(self.filename)):
            self.journal = module.EDJournal(Mock())
        self.journal.get_latest_log = lambda: str(self.filename)
        self.addCleanup(self.journal.log_file.close)

    def append(self, value):
        with self.filename.open('a') as stream:
            stream.write(value)
        stamp = self.filename.stat().st_mtime + 1
        os.utime(self.filename, (stamp, stamp))

    def test_initial_journal_replay_extracts_loadout_engineering_identity_and_zero_fuel(self):
        info = self.journal.ship_details()
        self.assertEqual(info['loadout'], self.loadout)
        self.assertIsNotNone(info['profile_key'])
        self.assertEqual(self.journal.ship_state()['fuel_percent'], 0)
        self.assertTrue(self.journal.ship_state()['has_sco_fsd'])
        self.assertFalse(self.journal.ship_state()['has_fuel_scoop'])

    def test_partial_writes_are_retried_without_dropping_the_loadout_or_killing_the_reader(self):
        event = json.dumps({'event': 'EngineerCraft', 'ShipID': 42, 'Slot': 'MainEngines'})
        self.append(event[:15])
        self.assertFalse(self.journal.ship_details()['stale'])
        self.append(event[15:] + '\n')
        self.assertTrue(self.journal.ship_details()['stale'])
        self.append(json.dumps(self.loadout) + '\n')
        self.assertFalse(self.journal.ship_details()['stale'])

    def test_ship_swap_does_not_display_the_previous_ships_equipment(self):
        self.append(json.dumps({'event': 'ShipyardSwap', 'ShipType': 'python', 'ShipID': 43}) + '\n')
        snapshot = self.journal.ship_details()
        self.assertIsNone(snapshot['loadout'])
        self.assertTrue(all(value is None for value in snapshot['equipment'].values()))

    def test_concurrent_controller_and_dashboard_reads_do_not_split_journal_records(self):
        events = [{'event': 'SetUserShipName', 'ShipID': 42, 'UserShipName': f'Ship {i}', 'UserShipId': f'ID{i}'} for i in range(20)]
        self.append(''.join(json.dumps(event) + '\n' for event in events))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.journal.ship_details(), range(40)))
        self.assertTrue(all(result['ship_name'] == 'Ship 19' for result in results))
        self.assertEqual(len({result['profile_key'] for result in results}), 1)


class RotationProfileGuardTests(unittest.TestCase):
    def test_all_rotation_axes_reject_a_changed_profile_before_sending_keys(self):
        rpy = types.ModuleType('RPYLineEditor')
        rpy.convert_curve_to_float = rpy.convert_curve_to_str = rpy.closest_angle = Mock()
        screen = types.ModuleType('Screen')
        screen.set_focus_elite_window = Mock()
        status = types.ModuleType('StatusParser')
        status.StatusParser = Mock()
        spec = importlib.util.spec_from_file_location('_ship_rotation_test', ROOT / 'EDShipControl.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'RPYLineEditor': rpy, 'Screen': screen, 'StatusParser': status}):
            spec.loader.exec_module(module)
        control = module.EDShipControl.__new__(module.EDShipControl)
        control.ap = Mock()
        control.keys = Mock()
        control.ap.require_current_ship_profile.side_effect = ValueError('Ship or outfitting changed')
        for method in (control.roll_clockwise_anticlockwise, control.pitch_up_down, control.yaw_right_left):
            with self.assertRaisesRegex(ValueError, 'outfitting changed'):
                method(30)
        control.keys.send.assert_not_called()
