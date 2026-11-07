"""Missing calibration must be reported before any assist can send game keys."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock

import backend_server
from calibration_status import ASSIST_REGIONS, inspect_calibration, valid_rect


def calibrated_data():
    data = {'Screen_Regions.full_panel': {'rect': [0, 0, 1, 1]},
            'EDGalaxyMap.full_panel': {'rect': [.05, .05, .95, .95]},
            'EDGalaxyMap.full_panel.subregion.cartographics': {'rect': [0, 0, .15, .075]}}
    for region in ('compass', 'target', 'sun', 'disengage', 'sco', 'missions'):
        data[f'Screen_Regions.full_panel.subregion.{region}'] = {'rect': [.1, .1, .9, .9]}
    return data


class CalibrationValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filename = Path(self.directory.name) / 'calibration.json'

    def write(self, data):
        self.filename.write_text(json.dumps(data), encoding='utf-8')
        return inspect_calibration(self.filename)

    def test_missing_unreadable_and_malformed_files_have_actionable_states(self):
        check = inspect_calibration(self.filename)
        self.assertEqual(check.state, 'missing')
        self.assertIn('does not exist', check.issues[0])
        self.assertEqual(set(check.blocked_assists), set(ASSIST_REGIONS))
        for text in ['{', 'null', '[]', '"not an object"', ' ' * (1024 * 1024 + 1)]:
            self.filename.write_text(text)
            self.assertEqual(inspect_calibration(self.filename).state, 'invalid')
        self.filename.unlink()
        self.filename.mkdir()
        self.assertEqual(inspect_calibration(self.filename).state, 'invalid')

    def test_zero_galaxy_map_bounds_block_waypoint_without_blocking_fsd(self):
        data = calibrated_data()
        data['EDGalaxyMap.full_panel']['rect'] = [0, 0, 0, 0]
        check = self.write(data)
        self.assertEqual(check.state, 'incomplete')
        self.assertIn('EDGalaxyMap.full_panel: invalid or empty bounds.', check.issues)
        self.assertIn('waypoint', check.blocked_assists)
        self.assertNotIn('fsd', check.blocked_assists)
        self.assertNotIn('sc', check.blocked_assists)

    def test_parent_subregions_and_direct_overrides_match_the_engine_loader(self):
        self.assertEqual(self.write(calibrated_data()).state, 'ready')
        data = calibrated_data()
        data['Screen_Regions.compass'] = {'rect': [0, 0, 0, 0]}
        self.assertIn('fsd', self.write(data).blocked_assists)
        data['Screen_Regions.compass']['rect'] = [.1, .1, .9, .9]
        del data['Screen_Regions.full_panel.subregion.compass']
        self.assertEqual(self.write(data).state, 'ready')
        del data['EDGalaxyMap.full_panel.subregion.cartographics']
        self.assertIn('waypoint', self.write(data).blocked_assists)

    def test_invalid_rectangles_are_rejected_including_nan_and_booleans(self):
        for rect in [None, [], [0, 0, 0, 1], [1, 0, 0, 1], [-.1, 0, .5, 1],
                     [0, 0, 1.1, 1], [0, 0, float('nan'), 1], [0, False, 1, 1], [0, 0, '1', 1]]:
            self.assertFalse(valid_rect(rect), rect)
        self.assertTrue(valid_rect([0, 0, 1, 1]))

    def test_optional_elw_scanner_calibration_is_checked_only_when_enabled(self):
        self.write(calibrated_data())
        self.assertEqual(inspect_calibration(self.filename).state, 'ready')
        check = inspect_calibration(self.filename, elw_scanner=True)
        self.assertIn('fsd', check.blocked_assists)
        self.assertNotIn('sc', check.blocked_assists)
        self.assertTrue(any('EDFSS.analysis' in issue for issue in check.issues))


class BackendCalibrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filename = Path(self.directory.name) / 'calibration.json'
        self.server = backend_server.EDAPEngineServer()
        self.server.calibration_file = self.filename
        self.server._loaded_calibration_fingerprint = None
        self.server.ed_ap = Mock(config={})
        self.ws = AsyncMock()

    async def test_missing_calibration_rejects_start_without_changing_flags_or_calling_engine(self):
        await self.server.handle_command(self.ws, {'command': 'start_waypoint'})
        self.server.ed_ap.set_waypoint_assist.assert_not_called()
        self.assertFalse(self.server.latest_telemetry['assists']['waypoint'])
        messages = [json.loads(call.args[0]) for call in self.ws.send.await_args_list]
        self.assertEqual(messages[0]['state'], 'missing')
        self.assertEqual(messages[1]['type'], 'command_error')
        self.assertIn('Save All Calibrations', messages[1]['message'])
        self.assertIn('restart', messages[1]['message'])
        await self.server.handle_command(self.ws, {'command': 'stop_waypoint'})
        self.server.ed_ap.set_waypoint_assist.assert_called_once_with(False)

    async def test_saved_calibration_needs_restart_before_it_can_be_used(self):
        data = calibrated_data()
        data['EDGalaxyMap.full_panel']['rect'] = [0, 0, 0, 0]
        self.filename.write_text(json.dumps(data))
        # Even though the new cockpit regions are valid, the live engine still
        # holds the old empty ones until restart.
        self.assertIn('fsd', self.server.get_calibration_status()['blocked_assists'])
        self.filename.write_text(json.dumps(calibrated_data()))
        status = self.server.get_calibration_status()
        self.assertEqual(status['state'], 'restart_required')
        self.assertTrue(status['restart_required'])
        await self.server.handle_command(self.ws, {'command': 'start_waypoint'})
        self.server.ed_ap.set_waypoint_assist.assert_not_called()
        # A newly started engine records the calibration it actually loaded.
        self.server._loaded_calibration_fingerprint = inspect_calibration(self.filename).fingerprint
        self.assertEqual(self.server.get_calibration_status()['state'], 'ready')
        await self.server.handle_command(self.ws, {'command': 'start_waypoint'})
        self.server.ed_ap.set_waypoint_assist.assert_called_once_with(True)
        self.assertTrue(self.server.latest_telemetry['assists']['waypoint'])

    async def test_recheck_reports_problems_while_explicit_mock_controls_still_work(self):
        self.server.mock_mode = True
        self.server.ed_ap = None
        await self.server.handle_command(self.ws, {'command': 'check_calibration'})
        status = json.loads(self.ws.send.await_args.args[0])
        self.assertEqual(status['state'], 'missing')
        self.assertTrue(status['mock'])
        self.assertEqual(status['blocked_assists'], [])
        await self.server.handle_command(self.ws, {'command': 'start_waypoint'})
        self.assertTrue(self.server.latest_telemetry['assists']['waypoint'])
