"""Regression checks for unauthorized network control and waypoint traversal."""
import asyncio
from contextlib import suppress
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import websockets
from websockets.exceptions import ConnectionClosedError, InvalidHandshake
import backend_server


class BackendNetworkSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.url = f'ws://127.0.0.1:{port}'
        self.settings = patch.multiple(backend_server, HOST='127.0.0.1', PORT=port)
        self.settings.start()
        self.server = backend_server.EDAPEngineServer()
        self.server.init_engine = Mock()
        self.task = asyncio.create_task(self.server.main())
        async with asyncio.timeout(5):
            while True:
                try:
                    async with websockets.connect(self.url):
                        break
                except OSError:
                    if self.task.done():
                        await self.task
                    await asyncio.sleep(0.01)

    async def asyncTearDown(self):
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task
        self.settings.stop()

    async def test_native_dashboard_connection_can_ping(self):
        async with websockets.connect(self.url) as ws:
            await ws.send(json.dumps({'command': 'ping'}))
            async with asyncio.timeout(3):
                while json.loads(await ws.recv()).get('type') != 'pong':
                    pass

    async def test_ping_advertises_correlated_waypoint_confirmation_support(self):
        async with websockets.connect(self.url) as ws:
            await ws.send(json.dumps({'command': 'ping', 'request_id': 'capability-check'}))
            async with asyncio.timeout(3):
                while True:
                    reply = json.loads(await ws.recv())
                    if reply.get('type') == 'pong':
                        break
            self.assertEqual(reply['request_id'], 'capability-check')
            self.assertIn('waypoint_load_result', reply['capabilities'])

    async def test_browser_origins_cannot_connect_directly_to_engine(self):
        for origin in ['https://attacker.example', 'http://127.0.0.1:3000', 'null']:
            with self.subTest(origin=origin):
                with self.assertRaises(InvalidHandshake):
                    async with websockets.connect(self.url, origin=origin):
                        self.fail('Browser handshake accepted')
        self.assertFalse(self.server.latest_telemetry['assists']['fsd'])

    async def test_oversized_commands_are_closed_without_stopping_engine(self):
        async with websockets.connect(self.url) as ws:
            await ws.recv()
            await ws.recv()
            await ws.recv()  # Initial calibration status.
            await ws.recv()  # Initial ship information.
            await ws.send('x' * (64 * 1024 + 1))
            with self.assertRaises(ConnectionClosedError) as caught:
                await ws.recv()
            self.assertEqual(caught.exception.rcvd.code, 1009)
        self.assertFalse(self.task.done())

    async def test_waypoint_loads_return_correlated_success_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            routes = Path(directory) / 'waypoints'
            routes.mkdir()
            (routes / 'route.json').write_text('{}')
            self.server.ed_ap = Mock()
            with patch.object(backend_server, 'WAYPOINT_DIR', routes):
                async with websockets.connect(self.url) as ws:
                    for accepted in [True, False]:
                        self.server.ed_ap.waypoint.load_waypoint_file.return_value = accepted
                        request_id = f'load-{accepted}'
                        await ws.send(json.dumps({'command': 'load_waypoint_file',
                                                  'filepath': 'waypoints/route.json', 'request_id': request_id}))
                        async with asyncio.timeout(3):
                            while True:
                                result = json.loads(await ws.recv())
                                if result.get('type') == 'waypoint_load_result':
                                    break
                        self.assertEqual(result['request_id'], request_id)
                        self.assertEqual(result['success'], accepted)
                    await ws.send(json.dumps({'command': 'load_waypoint_file',
                                              'filepath': '../outside.json', 'request_id': 'denied'}))
                    async with asyncio.timeout(3):
                        while True:
                            result = json.loads(await ws.recv())
                            if result.get('type') == 'waypoint_load_result':
                                break
                    self.assertEqual(result['request_id'], 'denied')
                    self.assertFalse(result['success'])


class BackendInputSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_waypoint_assist_cannot_have_its_route_replaced(self):
        server = backend_server.EDAPEngineServer()
        server.ed_ap = Mock()
        for telemetry_active, engine_active in [(True, False), (False, True)]:
            server.latest_telemetry['assists']['waypoint'] = telemetry_active
            server.ed_ap.waypoint_assist_enabled = engine_active
            with self.assertRaisesRegex(ValueError, 'Stop Waypoint Assist'):
                await server.handle_command(AsyncMock(), {'command': 'load_waypoint_file', 'filepath': 'waypoints/sample-route.json'})
        server.ed_ap.waypoint.load_waypoint_file.assert_not_called()

    async def test_public_bind_is_rejected_before_engine_initialization(self):
        server = backend_server.EDAPEngineServer()
        with patch.object(backend_server, 'HOST', '0.0.0.0'), patch.object(server, 'init_engine') as init:
            with self.assertRaisesRegex(ValueError, 'loopback'):
                await server.main()
            init.assert_not_called()

    async def test_waypoint_traversal_cannot_reach_the_loader(self):
        server = backend_server.EDAPEngineServer()
        server.ed_ap = Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            routes = root / 'waypoints'
            routes.mkdir()
            (routes / 'route.json').write_text('{}')
            outside = root / 'private.json'
            outside.write_text('{"private": true}')
            (routes / 'not-json.txt').write_text('private')
            (routes / 'large.json').write_bytes(b' ' * (1024 * 1024 + 1))
            with patch.object(backend_server, 'WAYPOINT_DIR', routes):
                for filepath in ['../private.json', str(outside), 'waypoints/../private.json',
                                 'waypoints/not-json.txt', 'waypoints/large.json',
                                 'waypoints/missing.json', '', None, 7]:
                    with self.subTest(filepath=filepath):
                        with self.assertRaises(ValueError):
                            await server.handle_command(AsyncMock(), {'command': 'load_waypoint_file', 'filepath': filepath})
                server.ed_ap.waypoint.load_waypoint_file.assert_not_called()
                await server.handle_command(AsyncMock(), {'command': 'load_waypoint_file', 'filepath': 'waypoints/route.json'})
                server.ed_ap.waypoint.load_waypoint_file.assert_called_once_with(str(routes / 'route.json'))

    async def test_waypoint_symlinks_cannot_escape_the_route_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            routes = root / 'waypoints'
            routes.mkdir()
            outside = root / 'private.json'
            outside.write_text('{}')
            try:
                (routes / 'link.json').symlink_to(outside)
            except OSError:
                self.skipTest('Creating symlinks is unavailable')
            with patch.object(backend_server, 'WAYPOINT_DIR', routes):
                with self.assertRaises(ValueError):
                    backend_server.resolve_waypoint_file('waypoints/link.json')
