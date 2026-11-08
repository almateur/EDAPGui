import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, Mock, patch

import backend_server
from test_ship_profiles import CoreHarness, ship
from ship_profiles import ShipProfiles
from EDAP_data import ship_rpy_sc_50


class BackendShipInfoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        folder = Path(self.directory.name)
        self.server = backend_server.EDAPEngineServer()
        self.core = CoreHarness(ship(), ShipProfiles(ship_rpy_sc_50, folder / 'profiles.json'), folder / 'Status.json')
        self.server.ed_ap = self.core
        self.ws = AsyncMock()

    async def test_ship_info_keeps_full_engineering_and_custom_payloads(self):
        await self.server.handle_command(self.ws, {'command': 'get_ship_info'})
        result = json.loads(self.ws.send.await_args.args[0])
        self.assertEqual(result['type'], 'ship_info')
        self.assertTrue(result['available'])
        self.assertEqual(result['loadout']['Modules'][0]['Engineering']['Modifiers'][0]['Value'], 1.42)
        self.assertEqual(result['loadout']['Modules'][0]['FutureModuleField'], {'keep': [1, 2, 3]})
        self.assertFalse(result['profile']['auto_tune'])

    async def test_tuning_controls_require_calibration_and_only_save_the_current_build(self):
        with patch.object(self.server, 'get_calibration_status', return_value={'state': 'missing'}):
            with self.assertRaisesRegex(ValueError, 'calibration'):
                await self.server.handle_command(self.ws, {'command': 'set_auto_tune_rpy', 'enabled': True})
        self.assertFalse(self.core.auto_tune_rpy)
        with patch.object(self.server, 'get_calibration_status', return_value={'state': 'ready'}):
            await self.server.handle_command(self.ws, {'command': 'set_auto_tune_rpy', 'enabled': True, 'request_id': 'enable'})
        reply = json.loads(self.ws.send.await_args.args[0])
        self.assertEqual(reply['type'], 'ship_action_result')
        self.assertEqual(reply['request_id'], 'enable')
        self.core.record_ship_tuning('RollRate', 45, 64)
        await self.server.handle_command(self.ws, {'command': 'save_ship_tuning', 'request_id': 'save'})
        self.assertFalse(self.core.ship_profile_manager.dirty)
        self.core.jn.ship_loadout.consume({'event': 'ModuleBuy', 'ShipID': 42})
        with self.assertRaisesRegex(ValueError, 'changed'):
            await self.server.handle_command(self.ws, {'command': 'save_ship_tuning'})
        await self.server.handle_command(self.ws, {'command': 'set_auto_tune_rpy', 'enabled': False})
        self.assertFalse(self.core.auto_tune_rpy)

    async def test_live_conditions_do_not_rebroadcast_large_loadouts_on_every_tick(self):
        self.server.broadcast = AsyncMock()
        await self.server.broadcast_ship_info()
        self.core._ship_status_data = {'Cargo': 2, 'timestamp': 'new'}
        await self.server.broadcast_ship_info()
        self.server.broadcast.assert_awaited_once()
        self.core.jn.ship_loadout.consume({'event': 'EngineerCraft', 'ShipID': 42})
        await self.server.broadcast_ship_info()
        self.assertEqual(self.server.broadcast.await_count, 2)

    async def test_mock_mode_reports_unavailable_instead_of_fabricating_a_ship(self):
        server = backend_server.EDAPEngineServer(mock=True)
        result = server.get_ship_info()
        self.assertFalse(result['available'])
        self.assertTrue(result['mock'])
        with self.assertRaisesRegex(ValueError, 'live backend'):
            await server.handle_command(self.ws, {'command': 'set_auto_tune_rpy', 'enabled': True})
