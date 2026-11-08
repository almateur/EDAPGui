from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from ship_loadout import ShipLoadout
from ship_profiles import ShipProfiles
from ship_profile_mixin import ShipProfileMixin
from EDAP_data import ship_rpy_sc_50

FIXTURE = Path(__file__).parent / 'fixtures/engineered-loadout.json'


def ship(ship_id=42, performance=1.42):
    tracker = ShipLoadout()
    tracker.consume({'event': 'LoadGame', 'FID': 'FTEST', 'Ship': 'python', 'ShipID': ship_id})
    event = json.loads(FIXTURE.read_text())
    event['ShipID'] = ship_id
    event['Modules'][0]['Engineering']['Modifiers'][0]['Value'] = performance
    tracker.consume(event)
    return tracker


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filename = Path(self.directory.name) / 'ship_configs.json'
        self.profiles = ShipProfiles(ship_rpy_sc_50, self.filename)

    def test_engineering_does_not_multiply_supercruise_estimates(self):
        self.profiles.select(ship(performance=1.42).summary())
        self.assertEqual(self.profiles.profile['RollRate'], ship_rpy_sc_50['python']['RollRate'])
        self.assertEqual(self.profiles.profile['PitchRate'], ship_rpy_sc_50['python']['PitchRate'])
        self.assertEqual(self.profiles.describe()['measured_points'], 0)
        self.assertEqual(set(self.profiles.describe()['curves']), {'Speed0', 'Speed50', 'Speed100', 'SCSpeed0', 'SCSpeed50', 'SCSpeed100'})

    def test_measurements_save_reload_and_restore_only_to_the_matching_ship_build(self):
        original = ship()
        self.profiles.select(original.summary())
        self.profiles.record('SCSpeed50', 'RollRate', 45, 62.5, {'pips': {'engine': 2}, 'cargo': 5})
        self.profiles.save(force=True)
        self.assertFalse(self.profiles.describe()['dirty'])
        self.profiles.select(ship(ship_id=43).summary())
        self.assertEqual(self.profiles.describe()['measured_points'], 0)
        self.assertEqual(self.profiles.profile['SCSpeed50']['RollRate']['45.0'], ship_rpy_sc_50['python']['RollRate'])
        self.profiles.select(ship(performance=1.43).summary())
        self.assertEqual(self.profiles.describe()['measured_points'], 0)
        self.profiles.select(original.summary())
        self.assertEqual(self.profiles.profile['SCSpeed50']['RollRate']['45.0'], 62.5)
        self.assertEqual(self.profiles.describe()['measured']['SCSpeed50']['RollRate']['45.0']['context']['cargo'], 5)
        reloaded = ShipProfiles(ship_rpy_sc_50, self.filename)
        reloaded.select(original.summary())
        self.assertEqual(reloaded.profile['SCSpeed50']['RollRate']['45.0'], 62.5)
        self.assertEqual(len(reloaded.data['Build_Profiles']), 3)

    def test_legacy_values_are_preserved_but_labelled_unverified_and_not_reused_for_changed_builds(self):
        legacy = {'Ship_Configs': {'python': {'RollRate': 61.0, 'CustomField': ['keep'], 'SCSpeed50': {'RollRate': {'45': 50, '5': 20}}}}, 'OtherSettings': {'keep': True}}
        self.filename.write_text(json.dumps(legacy))
        profiles = ShipProfiles(ship_rpy_sc_50, self.filename)
        profiles.select(ship().summary())
        self.assertEqual(profiles.profile['RollRate'], 61)
        self.assertEqual(profiles.describe()['seed_source'], 'legacy_unverified')
        self.assertEqual(profiles.describe()['measured_points'], 0)
        self.assertEqual(list(profiles.profile['SCSpeed50']['RollRate']), ['5.0', '45.0'])
        self.assertEqual(profiles.profile['CustomField'], ['keep'])
        self.assertEqual(profiles.data['Ship_Configs'], legacy['Ship_Configs'])
        profiles.select(ship(performance=1.43).summary())
        self.assertEqual(profiles.profile['RollRate'], ship_rpy_sc_50['python']['RollRate'])
        self.assertEqual(profiles.data['OtherSettings'], {'keep': True})

    def test_pending_identity_never_gets_a_persisted_or_shared_calibration(self):
        tracker = ship()
        tracker.consume({'event': 'ModuleBuy', 'ShipID': 42})
        self.profiles.select(tracker.summary())
        self.assertIsNone(self.profiles.key)
        self.assertFalse(self.profiles.record('SCSpeed50', 'YawRate', 30, 20))
        self.assertFalse(self.filename.exists())
        self.assertEqual(self.profiles.data['Build_Profiles'], {})

    def test_atomic_save_failure_preserves_previous_file_and_reports_dirty_state(self):
        self.profiles.select(ship().summary())
        original = self.filename.read_bytes()
        self.profiles.record('Speed50', 'YawRate', 30, 12)
        with patch('ship_profiles.os.replace', side_effect=PermissionError('file locked')):
            self.assertFalse(self.profiles.save(force=True))
        self.assertEqual(self.filename.read_bytes(), original)
        self.assertTrue(self.profiles.describe()['dirty'])
        self.assertIn('file locked', self.profiles.describe()['save_error'])
        self.assertFalse(list(self.filename.parent.glob('*.tmp')))
        self.profiles.save(force=True)
        self.assertFalse(self.profiles.describe()['dirty'])

    def test_corrupt_existing_files_are_not_overwritten(self):
        self.filename.write_text('{not json')
        with self.assertRaises(ValueError):
            ShipProfiles(ship_rpy_sc_50, self.filename)
        self.assertEqual(self.filename.read_text(), '{not json')


class CoreHarness(ShipProfileMixin):
    """Use the production profile adapter with a journal stub; no flight inputs."""
    def __init__(self, tracker, manager, status_file):
        self.jn = types.SimpleNamespace(ship_loadout=tracker,
            ship_state=lambda: {'type': tracker.ship_type, 'status': 'in_supercruise'},
            ship_details=tracker.snapshot)
        self.ship_profile_manager = manager
        self.ship_configs = manager.data
        self.current_ship_type = self.current_ship_cfg = None
        self.config = {'AutoTuneRPYRates': False}
        self.gui_loaded = False
        self.speed_demand = 'SCSpeed50'
        self._ship_status_data = None
        self.status = types.SimpleNamespace(file_path=status_file)
        self.ap_ckb = Mock()
        self.update_config = Mock()
        self.refresh_ship_profile()


class CoreProfileIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        folder = Path(self.directory.name)
        self.status_file = folder / 'Status.json'
        self.status_file.write_text(json.dumps({'Flags': 16, 'Pips': [4, 4, 4], 'Cargo': 12, 'Fuel': {'FuelMain': 10, 'FuelReservoir': .5}, 'timestamp': 'live'}))
        self.tracker = ship()
        self.manager = ShipProfiles(ship_rpy_sc_50, folder / 'ship_configs.json')
        self.core = CoreHarness(self.tracker, self.manager, self.status_file)

    def test_headless_controller_loads_and_updates_the_real_profile_without_gui_flag(self):
        self.assertFalse(self.core.gui_loaded)
        self.assertIs(self.core.current_ship_cfg, self.manager.profile)
        original_key = self.manager.key
        self.tracker.consume({'event': 'ModuleBuy', 'ShipID': 42})
        self.core.refresh_ship_profile()
        self.assertIsNone(self.manager.key)
        self.assertFalse(self.core.auto_tune_rpy)
        self.tracker.consume(json.loads(FIXTURE.read_text()))
        self.core.refresh_ship_profile()
        self.assertEqual(self.manager.key, original_key)
        self.core.ap_ckb.assert_any_call('log', unittest.mock.ANY)

    def test_switching_hulls_retains_template_refresh_in_headless_mode(self):
        self.core.templ = Mock()
        self.core.scr = types.SimpleNamespace(scaleX=1.1, scaleY=1.2)
        changed = json.loads(FIXTURE.read_text())
        changed.update(Ship='anaconda', ShipID=43)
        self.tracker.consume(changed)
        self.core.refresh_ship_profile()
        self.core.templ.reload_templates.assert_called_once_with(1.1, 1.2)

    def test_tuning_is_opt_in_bound_to_the_current_build_and_records_live_context(self):
        self.core.set_auto_tune_rpy(True)
        self.assertTrue(self.core.auto_tune_rpy)
        self.core.record_ship_tuning('RollRate', 45, 64)
        self.core.save_ship_tuning()
        info = self.core.get_ship_info()
        self.assertTrue(info['profile']['can_tune'])
        self.assertEqual(info['profile']['measured_points'], 1)
        point = info['profile']['measured']['SCSpeed50']['RollRate']['45.0']
        self.assertEqual(point['context']['pips']['engine'], 2)
        self.assertEqual(point['context']['cargo'], 12)
        self.assertEqual(info['loadout']['FutureShipField'], {'preserve': True})
        self.tracker.consume({'event': 'EngineerCraft', 'ShipID': 42})
        self.assertFalse(self.core.get_ship_info()['profile']['can_tune'])
        self.core.record_ship_tuning('YawRate', 30, 20)
        self.assertEqual(self.manager.describe()['measured_points'], 1)
        with self.assertRaisesRegex(ValueError, 'complete'):
            self.core.set_auto_tune_rpy(True)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.core.save_ship_tuning()
        self.core.set_auto_tune_rpy(False)
        self.assertFalse(self.core.auto_tune_rpy)

    def test_unknown_status_is_not_presented_as_zero_or_current(self):
        self.core.get_flight_info()
        self.status_file.write_text('{')
        info = self.core.get_flight_info()
        self.assertTrue(info['stale'])
        self.assertEqual(info['cargo'], 12)

    def test_gui_callback_can_save_on_another_thread_without_profile_deadlock(self):
        # Tk marshals worker callbacks to the main thread. A save on that thread
        # must not wait on a profile lock still held by the waiting worker.
        self.core.gui_loaded = True
        with ThreadPoolExecutor(max_workers=1) as executor:
            def callback(command, *args):
                if command == 'update_ship_cfg':
                    executor.submit(self.core.update_ship_configs).result(timeout=2)
            self.core.ap_ckb = callback
            changed = json.loads(FIXTURE.read_text())
            changed['ShipID'] = 43
            self.tracker.consume(changed)
            self.assertTrue(self.core.refresh_ship_profile())
