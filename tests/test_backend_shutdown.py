"""Process-level interrupt and live-engine cleanup regressions."""
import asyncio
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import unittest

import websockets

ROOT = Path(__file__).resolve().parents[1]


class BackendShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def launch(self, script=None):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        args = ['-c', script] if script else [str(ROOT / 'backend_server.py'), '--mock']
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, *args, cwd=ROOT,
            env={**os.environ, 'EDAP_HOST': '127.0.0.1', 'EDAP_PORT': str(self.port), 'PYTHONDONTWRITEBYTECODE': '1'},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)

    async def asyncTearDown(self):
        if hasattr(self, 'process') and self.process.returncode is None:
            self.process.kill()
            await self.process.communicate()

    def interrupt(self):
        # Windows process groups support CTRL_BREAK_EVENT, dispatched as SIGBREAK.
        self.process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)

    async def connect(self):
        async with asyncio.timeout(5):
            while True:
                try:
                    return await websockets.connect(f'ws://127.0.0.1:{self.port}')
                except OSError:
                    if self.process.returncode is not None:
                        self.fail('Backend exited before readiness')
                    await asyncio.sleep(0.02)

    async def assert_stopped(self, timeout=4):
        stdout, stderr = await asyncio.wait_for(self.process.communicate(), timeout)
        self.assertEqual(self.process.returncode, 130, stdout.decode() + stderr.decode())
        self.assertIn('Stopping backend', stderr.decode())
        self.assertNotIn('Task exception was never retrieved', stderr.decode())
        with socket.socket() as sock:
            sock.settimeout(1)
            self.assertNotEqual(sock.connect_ex(('127.0.0.1', self.port)), 0)
        return stdout.decode(), stderr.decode()

    async def test_interrupt_stops_ready_mock_backend_and_releases_listener(self):
        await self.launch()
        async with await self.connect() as ws:
            self.interrupt()
            await asyncio.wait_for(ws.wait_closed(), 3)
        await self.assert_stopped()

    async def test_first_interrupt_cancels_synchronous_startup(self):
        await self.launch('''
import time
import backend_server
class WaitingServer(backend_server.EDAPEngineServer):
    def init_engine(self):
        print('initializing', flush=True)
        while True: time.sleep(0.05)
raise SystemExit(backend_server.run_server(WaitingServer()))
''')
        self.assertEqual((await asyncio.wait_for(self.process.stdout.readline(), 5)).strip(), b'initializing')
        self.interrupt()
        await self.assert_stopped()

    async def test_interrupt_calls_live_quit_and_stops_non_daemon_engine_thread(self):
        await self.launch('''
import threading
import backend_server
class Engine:
    def __init__(self):
        self.stopped = threading.Event()
        self.ap_thread = threading.Thread(target=self.stopped.wait)
        self.ap_thread.start()
    def __getattr__(self, name):
        if name.startswith('set_'): return lambda *args: None
        raise AttributeError(name)
    def quit(self):
        self.stopped.set()
        print('engine-cleaned', flush=True)
class LiveServer(backend_server.EDAPEngineServer):
    def init_engine(self): self.ed_ap = Engine()
raise SystemExit(backend_server.run_server(LiveServer()))
''')
        async with await self.connect() as ws:
            self.interrupt()
            await asyncio.wait_for(ws.wait_closed(), 3)
        stdout, _ = await self.assert_stopped()
        self.assertIn('engine-cleaned', stdout)

    async def blocked_cleanup(self):
        await self.launch('''
import time
import backend_server
class Engine:
    def __getattr__(self, name):
        if name.startswith('set_'): return lambda *args: None
        raise AttributeError(name)
    def quit(self):
        print('cleanup-blocked', flush=True)
        while True: time.sleep(0.05)
class LiveServer(backend_server.EDAPEngineServer):
    def init_engine(self): self.ed_ap = Engine()
raise SystemExit(backend_server.run_server(LiveServer()))
''')
        ws = await self.connect()
        self.interrupt()
        self.assertEqual((await asyncio.wait_for(self.process.stdout.readline(), 5)).strip(), b'cleanup-blocked')
        return ws

    async def test_second_interrupt_forces_exit_if_cleanup_blocks(self):
        ws = await self.blocked_cleanup()
        try:
            self.interrupt()
            await self.assert_stopped(timeout=3)
        finally:
            await ws.close()

    async def test_shutdown_deadline_forces_exit_if_cleanup_blocks(self):
        ws = await self.blocked_cleanup()
        try:
            await self.assert_stopped(timeout=7)
        finally:
            await ws.close()


if __name__ == '__main__':
    unittest.main()
