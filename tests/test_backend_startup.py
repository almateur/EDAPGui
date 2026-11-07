"""Explicit mock startup must not touch game/OCR dependencies."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch

import websockets
import backend_server

ROOT = Path(__file__).resolve().parents[1]


class BackendStartupTests(unittest.TestCase):
    def test_import_and_explicit_mock_skip_all_game_dependencies(self):
        script = '''
import builtins
original = builtins.__import__
attempts = []
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'ED_AP', 'cv2', 'paddle', 'paddleocr', 'ultralytics', 'torch', 'win32gui', 'keyboard'}:
        attempts.append(name)
        raise AssertionError('Unexpected game dependency import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import backend_server
server = backend_server.EDAPEngineServer(mock=True)
server.init_engine()
assert attempts == [], attempts
assert server.ed_ap is None
assert server.latest_telemetry['status'] == 'Mock mode'
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_startup_still_constructs_live_engine(self):
        core = types.ModuleType('ED_AP')
        core.EDAutopilot = Mock()
        cv = types.ModuleType('cv2')
        server = backend_server.EDAPEngineServer()
        with patch.dict(sys.modules, {'ED_AP': core, 'cv2': cv}), patch.object(backend_server, 'cv2', None):
            server.init_engine()
        core.EDAutopilot.assert_called_once_with(cb=server.ap_callback, do_thread=True)
        self.assertIs(server.ed_ap, core.EDAutopilot.return_value)
        self.assertFalse(server.mock_mode)

    def test_failed_live_initialization_retains_automatic_mock_fallback(self):
        core = types.ModuleType('ED_AP')
        core.EDAutopilot = Mock(side_effect=RuntimeError('engine unavailable'))
        server = backend_server.EDAPEngineServer()
        with patch.dict(sys.modules, {'ED_AP': core, 'cv2': types.ModuleType('cv2')}), patch.object(backend_server, 'cv2', None):
            server.init_engine()
        self.assertIsNone(server.ed_ap)
        self.assertTrue(server.mock_mode)
        self.assertEqual(server.latest_telemetry['status'], 'Mock mode')


class MockBackendCommandLineTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_cli_serves_telemetry_and_confirms_sample_route(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / 'backend_server.py'), '--mock', cwd=ROOT,
            env={**os.environ, 'EDAP_HOST': '127.0.0.1', 'EDAP_PORT': str(port), 'PYTHONDONTWRITEBYTECODE': '1'},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            async with asyncio.timeout(5):
                while True:
                    try:
                        ws = await websockets.connect(f'ws://127.0.0.1:{port}')
                        break
                    except OSError:
                        if process.returncode is not None:
                            self.fail('Mock backend exited before becoming ready')
                        await asyncio.sleep(0.02)
            async with ws:
                telemetry = json.loads(await ws.recv())
                self.assertEqual(telemetry['data']['status'], 'Mock mode')
                self.assertIn('mock mode', json.loads(await ws.recv())['message'])
                await ws.send(json.dumps({'command': 'load_waypoint_file', 'filepath': 'waypoints/sample-route.json', 'request_id': 'mock-load'}))
                async with asyncio.timeout(3):
                    while True:
                        reply = json.loads(await ws.recv())
                        if reply.get('type') == 'waypoint_load_result':
                            break
                self.assertTrue(reply['success'])
                self.assertEqual(reply['request_id'], 'mock-load')
                self.assertIn('mock mode', reply['message'])
                await ws.send(json.dumps({'command': 'stop_all_assists'}))
                async with asyncio.timeout(3):
                    while True:
                        reply = json.loads(await ws.recv())
                        if reply.get('type') == 'telemetry':
                            break
                self.assertEqual(reply['data']['status'], 'Mock mode')
        finally:
            if process.returncode is None:
                process.terminate()
            stdout, stderr = await asyncio.wait_for(process.communicate(), 5)
        self.assertIn('Mock mode requested', stderr.decode())
        self.assertNotIn('Creating model:', stdout.decode() + stderr.decode())


if __name__ == '__main__':
    unittest.main()
