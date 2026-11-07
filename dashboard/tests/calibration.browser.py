"""Build dashboard first; requires Python Playwright/websockets and Chromium.

The real Python protocol and Node dashboard run with a stub game engine.
EDAP_TEST_CHROMIUM selects a system browser; EDAP_TEST_SCREENSHOTS saves evidence.
"""
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import types
from unittest.mock import patch
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import backend_server
from calibration_status import inspect_calibration


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def calibration():
    data = {'Screen_Regions.full_panel': {'rect': [0, 0, 1, 1]},
            'EDGalaxyMap.full_panel': {'rect': [.05, .05, .95, .95]},
            'EDGalaxyMap.full_panel.subregion.cartographics': {'rect': [0, 0, .15, .075]}}
    for name in ('compass', 'target', 'sun', 'disengage', 'sco', 'missions'):
        data[f'Screen_Regions.full_panel.subregion.{name}'] = {'rect': [.1, .1, .9, .9]}
    return data


async def main():
    ui_port, engine_port = port(), port()
    origin = f'http://127.0.0.1:{ui_port}'
    dashboard = task = None
    calls, errors = [], []
    with tempfile.TemporaryDirectory() as directory, patch.multiple(backend_server, HOST='127.0.0.1', PORT=engine_port):
        filename = Path(directory) / 'calibration.json'
        with (Path(directory) / 'dashboard.log').open('w') as log:
            def start_backend():
                server = backend_server.EDAPEngineServer()
                server.calibration_file = filename
                server._loaded_calibration_fingerprint = inspect_calibration(filename).fingerprint
                engine = types.SimpleNamespace(config={}, ap_thread=None)
                for method in ('set_fsd_assist', 'set_sc_assist', 'set_robigo_assist', 'set_dss_assist',
                               'set_single_waypoint_assist', 'set_afk_combat_assist', 'quit'):
                    setattr(engine, method, lambda *args: None)
                engine.set_waypoint_assist = lambda enabled: calls.append(enabled)
                server.init_engine = lambda: setattr(server, 'ed_ap', engine)
                return asyncio.create_task(server.main())

            try:
                task = start_backend()
                dashboard = await asyncio.create_subprocess_exec('node', str(ROOT / 'dashboard/dist/server.js'), cwd=ROOT,
                    env={**os.environ, 'PORT': str(ui_port), 'ENGINE_WS_URL': f'ws://127.0.0.1:{engine_port}'}, stdout=log, stderr=log)
                async with async_playwright() as p:
                    browser_path = os.environ.get('EDAP_TEST_CHROMIUM') or shutil.which('chromium')
                    browser = await p.chromium.launch(headless=True, **({'executable_path': browser_path} if browser_path else {}))
                    page = await browser.new_page(viewport={'width': 1280, 'height': 1000})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    await page.add_init_script('''const Original = window.WebSocket;
                        window.WebSocket = class extends Original {
                            constructor(...args) { super(...args); window.edapTestSocket = this; }
                        };''')
                    await page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    await page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                    async with asyncio.timeout(15):
                        while True:
                            try:
                                if (await page.request.get(origin + '/api/health')).ok:
                                    break
                            except Exception:
                                pass
                            await asyncio.sleep(.05)
                    await page.goto(origin, wait_until='domcontentloaded')
                    card = page.locator('.calibration-card')
                    start = page.get_by_role('button', name='Start Waypoint Assist')
                    recheck = page.get_by_role('button', name='Recheck calibration')
                    await expect(card).to_contain_text('Screen calibration is missing.')
                    await expect(card).to_contain_text('Save All Calibrations')
                    await expect(start).to_be_disabled()
                    await expect(page.get_by_role('button', name='STOP ALL ASSISTS')).to_be_enabled()
                    # A stale client can bypass the disabled button; Python must
                    # reject it before calling the game engine.
                    await page.evaluate("window.edapTestSocket.send(JSON.stringify({command:'start_waypoint'}))")
                    await expect(page.locator('.assist-error')).to_contain_text('Cannot start waypoint assist')
                    assert True not in calls
                    await page.reload(wait_until='domcontentloaded')
                    await expect(card).to_contain_text('Screen calibration is missing.')
                    await expect(start).to_be_disabled()
                    filename.write_text('{')
                    await recheck.click()
                    await expect(card).to_contain_text('unreadable or invalid')
                    await expect(card).to_contain_text('Back up and rename')
                    data = calibration()
                    data['EDGalaxyMap.full_panel']['rect'] = [0, 0, 0, 0]
                    filename.write_text(json.dumps(data))
                    await recheck.click()
                    await expect(card).to_contain_text('EDGalaxyMap.full_panel: invalid or empty bounds')
                    await expect(start).to_be_disabled()
                    await expect(page.get_by_role('button', name='Start FSD Assist')).to_be_disabled()
                    filename.write_text(json.dumps(calibration()))
                    await recheck.click()
                    await expect(card).to_contain_text('Restart backend to load calibration')
                    await expect(start).to_be_disabled()
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    task = start_backend()
                    await expect(card).to_contain_text('Screen calibration configured', timeout=15000)
                    await expect(start).to_be_enabled()
                    await start.click()
                    await expect(page.get_by_role('button', name='Stop Waypoint Assist')).to_be_enabled()
                    assert True in calls
                    # Missing data must never disable an already active stop.
                    filename.unlink()
                    await recheck.click()
                    await expect(card).to_contain_text('Screen calibration is missing.')
                    await page.get_by_role('button', name='Stop Waypoint Assist').click()
                    await expect(start).to_be_disabled()
                    assert calls[-1] is False
                    await page.locator('.calibration-issues summary').click()
                    screenshots = os.environ.get('EDAP_TEST_SCREENSHOTS')
                    if screenshots:
                        Path(screenshots).mkdir(parents=True, exist_ok=True)
                        await card.screenshot(path=str(Path(screenshots) / 'calibration-required.png'))
                    await page.set_viewport_size({'width': 390, 'height': 844})
                    assert await card.evaluate('(el) => el.scrollWidth <= el.clientWidth')
                    if screenshots:
                        await card.screenshot(path=str(Path(screenshots) / 'calibration-required-mobile.png'))
                    assert not errors, errors
                    await browser.close()
                    print('PASS: missing/invalid/empty calibration, start rejection before engine calls, page reload, restart requirement, recovered starts, always-available stop and mobile layout.')
            finally:
                if dashboard and dashboard.returncode is None:
                    dashboard.terminate()
                    await asyncio.wait_for(dashboard.wait(), 5)
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task


asyncio.run(main())
