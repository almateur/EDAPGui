"""Real journal/profile/backend/dashboard flow, with synthetic game files and no flight inputs.

Build first. Requires Python websockets/Playwright and Chromium. The measured
sample is injected by the test; live Windows capture is not simulated.
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
from unittest.mock import Mock, patch
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import backend_server
from calibration_status import inspect_calibration
from test_calibration_status import calibrated_data
from test_ship_journal import journal_module
from test_ship_profiles import CoreHarness
from ship_profiles import ShipProfiles
from EDAP_data import ship_rpy_sc_50


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def main():
    ui_port, engine_port = port(), port()
    origin = f'http://127.0.0.1:{ui_port}'
    dashboard = task = ticker = journal = None
    errors = []
    with tempfile.TemporaryDirectory() as directory, patch.multiple(backend_server, HOST='127.0.0.1', PORT=engine_port):
        folder = Path(directory)
        log_path = folder / 'dashboard.log'
        journal_path = folder / 'Journal.test.log'
        status_path = folder / 'Status.json'
        profile_path = folder / 'ship_configs.json'
        calibration_path = folder / 'ocr_calibration.json'
        calibration_path.write_text(json.dumps(calibrated_data()))
        journal_path.write_text(json.dumps({'event': 'LoadGame', 'FID': 'FTEST', 'Ship': 'python', 'ShipID': 42}) + '\n')
        status = {'timestamp': '2026-11-08T10:00:00Z', 'Flags': 16, 'Pips': [4, 4, 4], 'Cargo': 12,
                  'Fuel': {'FuelMain': 12.3, 'FuelReservoir': .5}, 'FutureStatusField': {'preserve': True}}
        status_path.write_text(json.dumps(status))
        game_loadout = json.loads((ROOT / 'tests/fixtures/engineered-loadout.json').read_text())
        with log_path.open('w') as log:
            module = journal_module()
            with patch.object(module.EDJournal, 'get_latest_log', return_value=str(journal_path)):
                journal = module.EDJournal(Mock())
            journal.get_latest_log = lambda: str(journal_path)
            core = CoreHarness(journal.ship_loadout, ShipProfiles(ship_rpy_sc_50, profile_path), status_path)
            core.jn = journal
            core.ap_thread = None
            core.quit = lambda: core.ship_profile_manager.save(force=True)
            for method in ('set_fsd_assist', 'set_sc_assist', 'set_waypoint_assist', 'set_robigo_assist', 'set_dss_assist', 'set_single_waypoint_assist', 'set_afk_combat_assist'):
                setattr(core, method, lambda *args: None)
            server = backend_server.EDAPEngineServer()
            server.calibration_file = calibration_path
            server._loaded_calibration_fingerprint = inspect_calibration(calibration_path).fingerprint
            server.init_engine = lambda: setattr(server, 'ed_ap', core)

            def append(event):
                with journal_path.open('a') as stream:
                    stream.write(json.dumps(event) + '\n')
                stamp = journal_path.stat().st_mtime + 1
                os.utime(journal_path, (stamp, stamp))

            async def refresh_idle_controller():
                while True:
                    core.refresh_ship_profile()
                    await asyncio.sleep(.1)

            try:
                task = asyncio.create_task(server.main())
                ticker = asyncio.create_task(refresh_idle_controller())
                dashboard = await asyncio.create_subprocess_exec('node', str(ROOT / 'dashboard/dist/server.js'), cwd=ROOT,
                    env={**os.environ, 'PORT': str(ui_port), 'ENGINE_WS_URL': f'ws://127.0.0.1:{engine_port}'}, stdout=log, stderr=log)
                async with async_playwright() as p:
                    browser_path = os.environ.get('EDAP_TEST_CHROMIUM') or shutil.which('chromium')
                    browser = await p.chromium.launch(headless=True, **({'executable_path': browser_path} if browser_path else {}))
                    page = await browser.new_page(viewport={'width': 1440, 'height': 1100})
                    page.on('pageerror', lambda error: errors.append(str(error)))
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
                    card = page.locator('.ship-info-card')
                    tune = card.get_by_role('checkbox', name='Learn rotation rates during assists')
                    refresh = card.get_by_role('button', name='Refresh ship data')
                    await expect(card.locator('.ship-warning')).to_contain_text('Waiting')
                    await expect(tune).to_be_disabled()
                    append(game_loadout)
                    await expect(card).to_contain_text('Test Explorer', timeout=10000)
                    await expect(tune).to_be_enabled()
                    await expect(tune).not_to_be_checked()
                    key = core.ship_profile_manager.key
                    await expect(card.locator('.rate-grid')).to_contain_text('90')
                    await expect(card.locator('.equipment-list')).to_contain_text('SCO FSD: Fitted')
                    await card.get_by_text('Reported ship statistics', exact=False).click()
                    await expect(card.locator('.stats-grid')).to_contain_text('Unladen Mass')
                    await expect(card.locator('.stats-grid')).to_contain_text('540')
                    await card.locator('.module-details > summary').click()
                    search = card.get_by_role('searchbox', name='Search ship modules')
                    await search.fill('Thrusters')
                    await card.get_by_role('checkbox', name='Engineered only').check()
                    await card.get_by_role('button', name='Inspect MainEngines').click()
                    await expect(card.locator('.module-expanded')).to_contain_text('Professor Palin')
                    await expect(card.locator('.module-expanded')).to_contain_text('Drag Drives')
                    await expect(card.locator('.modifier-table')).to_contain_text('1.42')
                    await expect(card.locator('.modifier-table')).to_contain_text('1,360')
                    await card.get_by_text('All module fields', exact=True).click()
                    await expect(card.locator('.module-expanded pre')).to_contain_text('FutureModuleField')
                    await tune.click()
                    await expect(tune).to_be_checked()
                    # Exercise persistence/UI with a deterministic observation;
                    # this is not a claim that the browser measures a real ship.
                    core.record_ship_tuning('RollRate', 45, 64)
                    await card.get_by_role('button', name='Save tuning now').click()
                    await expect(card).to_contain_text('Tuning saved for this ship and build.')
                    await expect(card.locator('.tuning-source')).to_contain_text('1 measured curve point')
                    saved = json.loads(profile_path.read_text())['Build_Profiles'][key]
                    assert saved['SCSpeed50']['RollRate']['45.0'] == 64
                    assert saved['_Meta']['measured']['SCSpeed50']['RollRate']['45.0']['context']['cargo'] == 12
                    await card.get_by_text('Tuning curves and measured points', exact=True).click()
                    await expect(card.locator('.curve-grid')).to_contain_text('Measured')
                    await expect(card.locator('.curve-grid')).to_contain_text('64')

                    async def export():
                        async with page.expect_download() as event:
                            await card.get_by_role('button', name='Export ship JSON').click()
                        download = await event.value
                        output = folder / download.suggested_filename
                        await download.save_as(output)
                        return json.loads(output.read_text())

                    exported = await export()
                    assert exported['loadout'] == game_loadout
                    assert exported['live_flight']['pips']['engine'] == 2
                    assert 'FTEST' not in json.dumps(exported)
                    status.update(Cargo=0, Pips=[0, 8, 4], Fuel={'FuelMain': 0, 'FuelReservoir': .25})
                    status_path.write_text(json.dumps(status))
                    await expect(card.locator('.ship-summary')).to_contain_text('0 t', timeout=5000)
                    await refresh.click()
                    exported = await export()
                    assert exported['raw_status']['FutureStatusField'] == {'preserve': True}
                    assert exported['live_flight']['pips']['engine'] == 4
                    assert core.ship_profile_manager.key == key
                    await page.reload(wait_until='domcontentloaded')
                    await expect(card).to_contain_text('Test Explorer')
                    await expect(card.locator('.tuning-source')).to_contain_text('1 measured curve point')
                    append({'event': 'SetUserShipName', 'ShipID': 42, 'UserShipName': 'Renamed Explorer', 'UserShipId': 'RENAMED'})
                    await expect(card).to_contain_text('Renamed Explorer')
                    assert core.ship_profile_manager.key == key

                    other = json.loads(json.dumps(game_loadout))
                    other['ShipID'] = 43
                    other['ShipName'] = 'Second Python'
                    append(other)
                    await expect(card).to_contain_text('Second Python')
                    await expect(card.locator('.tuning-source')).to_contain_text('measurement needed')
                    assert core.ship_profile_manager.key != key
                    append(game_loadout)
                    await expect(card.locator('.tuning-source')).to_contain_text('1 measured curve point')
                    changed = json.loads(json.dumps(game_loadout))
                    changed['Modules'][0]['Engineering']['Modifiers'][0]['Value'] = 1.43
                    append(changed)
                    await expect(card.locator('.tuning-source')).to_contain_text('measurement needed')
                    assert core.ship_profile_manager.key != key
                    append(game_loadout)
                    await expect(card.locator('.tuning-source')).to_contain_text('1 measured curve point')
                    append({'event': 'EngineerCraft', 'ShipID': 42, 'Slot': 'MainEngines'})
                    await expect(card.locator('.ship-warning')).to_contain_text('engineering changed')
                    await expect(card).to_contain_text('Learning is paused')
                    await tune.click()  # Turning the preference off must remain possible while paused.
                    await expect(tune).not_to_be_checked()
                    await expect(tune).to_be_disabled()
                    append(game_loadout)
                    await expect(tune).to_be_enabled()
                    await expect(tune).not_to_be_checked()
                    await card.locator('.module-details > summary').click()
                    await card.get_by_role('button', name='Inspect MainEngines').click()
                    screenshots = os.environ.get('EDAP_TEST_SCREENSHOTS')
                    if screenshots:
                        Path(screenshots).mkdir(parents=True, exist_ok=True)
                        await card.screenshot(path=str(Path(screenshots) / 'ship-engineering.png'))
                    await page.set_viewport_size({'width': 390, 'height': 844})
                    assert await card.evaluate('(el) => el.scrollWidth <= el.clientWidth')
                    if screenshots:
                        await card.screenshot(path=str(Path(screenshots) / 'ship-engineering-mobile.png'))
                    assert not errors, errors
                    await browser.close()
                    print('PASS: journal extraction, engineering inspection, live status, JSON export, opt-in learning, atomic save, reload, distinct ships/builds, restored tuning, stale-data pause/off and mobile layout.')
            finally:
                if ticker:
                    ticker.cancel()
                    with suppress(asyncio.CancelledError):
                        await ticker
                if dashboard and dashboard.returncode is None:
                    dashboard.terminate()
                    await asyncio.wait_for(dashboard.wait(), 5)
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                journal.log_file.close()


asyncio.run(main())
