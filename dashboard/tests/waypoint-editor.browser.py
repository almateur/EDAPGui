"""Browser regression: build dashboard first; requires Python Playwright and a browser.

EDAP_TEST_PYTHON selects Python with websockets installed; EDAP_TEST_CHROMIUM
optionally selects a system browser. The game and OCR packages are not needed.
"""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


async def stop(process):
    if process and process.returncode is None:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 8)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


async def main():
    port, engine_port = free_port(), free_port()
    origin = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'PORT': str(port), 'EDAP_HOST': '127.0.0.1', 'EDAP_PORT': str(engine_port),
           'ENGINE_WS_URL': f'ws://127.0.0.1:{engine_port}', 'PYTHONDONTWRITEBYTECODE': '1'}
    sent, errors = [], []
    backend = dashboard = None
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        source = folder / 'my-route.json'
        original = (ROOT / 'waypoints/sample-route.json').read_bytes()
        source.write_bytes(original)
        log_path = folder / 'servers.log'
        with log_path.open('w') as log:
            try:
                backend = await asyncio.create_subprocess_exec(os.environ.get('EDAP_TEST_PYTHON', sys.executable),
                    str(ROOT / 'backend_server.py'), '--mock', cwd=ROOT, env=env, stdout=log, stderr=log)
                dashboard = await asyncio.create_subprocess_exec('node', str(ROOT / 'dashboard/dist/server.js'),
                    cwd=ROOT, env=env, stdout=log, stderr=log)
                async with async_playwright() as p:
                    browser_path = os.environ.get('EDAP_TEST_CHROMIUM') or shutil.which('chromium')
                    browser = await p.chromium.launch(headless=True, **({'executable_path': browser_path} if browser_path else {}))
                    page = await browser.new_page(viewport={'width': 1440, 'height': 1100})
                    page.on('pageerror', lambda error: errors.append(str(error)))

                    def record(frame):
                        command = json.loads(frame)
                        if command.get('command') == 'load_waypoint_file':
                            sent.append(command)
                    page.on('websocket', lambda ws: ws.on('framesent', record))
                    await page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    await page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                    async with asyncio.timeout(15):
                        while True:
                            try:
                                if (await page.request.get(origin + '/api/health')).ok:
                                    break
                            except Exception:
                                pass
                            if dashboard.returncode is not None:
                                raise AssertionError('Dashboard exited before becoming ready')
                            await asyncio.sleep(.05)
                    await page.goto(origin, wait_until='domcontentloaded')
                    await expect(page.locator('#connection-status')).to_contain_text('Connected to EDAP Python Engine', timeout=15000)
                    picker = page.get_by_role('button', name='Load File', exact=True)
                    apply = page.get_by_role('button', name='Apply changes', exact=True)
                    download = page.get_by_role('button', name='Download JSON', exact=True)
                    timeline = page.locator('.route-stop')

                    async def choose(file):
                        async with page.expect_file_chooser() as chooser:
                            await picker.click()
                        await (await chooser.value).set_files(file)

                    async def export():
                        async with page.expect_download() as event:
                            await download.click()
                        result = await event.value
                        destination = folder / result.suggested_filename
                        await result.save_as(destination)
                        return json.loads(destination.read_text())

                    await choose(str(source))
                    await expect(page.locator('.route-state')).to_have_text('Applied to backend')
                    await expect(timeline).to_have_count(2)
                    await expect(timeline.first).to_contain_text('Eravate')
                    await page.get_by_role('textbox', name='System', exact=True).fill('Sol')
                    await page.get_by_role('textbox', name='Station', exact=True).fill('Galileo')
                    await page.get_by_role('textbox', name='Comment', exact=True).fill('My edited destination')
                    await page.get_by_label('Completed', exact=True).check()
                    buy = page.locator('.trade-grid .commodities').nth(0)
                    sell = page.locator('.trade-grid .commodities').nth(1)
                    await buy.get_by_role('button', name='Add commodity').click()
                    await expect(apply).to_be_disabled()
                    await page.get_by_label('Buy commodity 1', exact=True).fill('Gold')
                    await page.get_by_label('Buy quantity 1', exact=True).fill('10')
                    await sell.get_by_role('button', name='Add commodity').click()
                    await page.get_by_label('Sell commodity 1', exact=True).fill('All')
                    await page.get_by_label('Fleet carrier transfer', exact=True).check()
                    await page.locator('.stop-editor').get_by_label('Update commodity counts', exact=True).check()
                    await page.get_by_text('Bookmarks', exact=True).click()
                    await page.get_by_label('Galaxy bookmark type', exact=True).fill('Sys')
                    await page.get_by_label('Galaxy bookmark number', exact=True).fill('2')
                    await page.get_by_role('button', name='Move stop down', exact=True).click()
                    await expect(timeline.first).to_contain_text('Kremainn')
                    await page.get_by_role('button', name='+ Add stop', exact=True).click()
                    await expect(apply).to_be_disabled()
                    await expect(page.locator('.route-validation')).to_contain_text('enter a system')
                    await page.get_by_role('textbox', name='System', exact=True).fill('Achenar')
                    await page.get_by_label('Skip stop', exact=True).check()
                    await page.get_by_role('button', name='+ Repeat route', exact=True).click()
                    await expect(timeline).to_have_count(4)
                    await expect(timeline.last).to_contain_text('Repeat route')
                    await page.get_by_role('button', name='Move stop up', exact=True).click()
                    await expect(page.locator('.route-validation')).to_contain_text('REPEAT stop to the end')
                    await page.get_by_role('button', name='Move stop down', exact=True).click()
                    await page.locator('.shopping-editor summary').click()
                    await page.locator('.shopping-editor').get_by_label('Update commodity counts', exact=True).check()
                    await page.locator('.shopping-editor').get_by_role('button', name='Add commodity').click()
                    await page.get_by_label('Global buy commodity 1', exact=True).fill('Silver')
                    await page.get_by_label('Global buy quantity 1', exact=True).fill('5')
                    await expect(apply).to_be_enabled()
                    draft = await export()
                    keys = [key for key in draft if key != 'GlobalShoppingList']
                    assert [draft[key]['SystemName'] for key in keys] == ['Kremainn', 'Sol', 'Achenar', 'REPEAT']
                    sol = draft[keys[1]]
                    assert sol['StationName'] == 'Galileo' and sol['Comment'] == 'My edited destination'
                    assert sol['BuyCommodities'] == {'Gold': 10} and sol['SellCommodities'] == {'All': 0}
                    assert sol['Completed'] and sol['FleetCarrierTransfer'] and sol['UpdateCommodityCount']
                    assert sol['GalaxyBookmarkType'] == 'Sys' and sol['GalaxyBookmarkNumber'] == 2
                    assert draft['GlobalShoppingList']['BuyCommodities'] == {'Silver': 5}
                    assert draft['GlobalShoppingList']['Skip']  # Preserved legacy field; the engine ignores it.
                    assert draft['GlobalShoppingList']['UpdateCommodityCount']
                    await apply.click()
                    await expect(page.locator('.route-state')).to_have_text('Applied to backend')
                    saved = json.loads((ROOT / sent[-1]['filepath']).read_text())
                    assert list(saved) == list(draft) and saved == draft
                    assert source.read_bytes() == original
                    # Backend rejection must retain the editable draft and permit retry.
                    await timeline.nth(1).click()
                    comment = page.locator('.stop-editor').get_by_role('textbox', name='Comment', exact=True)
                    await comment.fill('Keep this draft after a rejected apply')
                    await page.route('**/api/waypoints/import', lambda route: route.fulfill(status=201,
                        content_type='application/json', body=json.dumps({'filepath': 'waypoints/missing-editor-test.json'})))
                    await apply.click()
                    await expect(page.locator('.waypoint-card [role=alert]')).to_contain_text('missing')
                    await expect(page.locator('.route-state')).to_have_text('Edited draft')
                    await expect(comment).to_have_value('Keep this draft after a rejected apply')
                    await expect(apply).to_be_enabled()
                    await page.unroute('**/api/waypoints/import')
                    await page.get_by_role('button', name='Undo edits', exact=True).click()
                    await page.get_by_role('button', name='Reset completion', exact=True).click()
                    await expect(page.locator('.route-state')).to_have_text('Edited draft')
                    await page.get_by_role('button', name='Undo edits', exact=True).click()
                    await expect(page.locator('.route-state')).to_have_text('Applied to backend')
                    await timeline.last.click()
                    await page.get_by_role('button', name='Remove stop', exact=True).click()
                    await expect(timeline).to_have_count(3)
                    # Reject discarding a draft, then explicitly keep it by downloading.
                    page.once('dialog', lambda dialog: dialog.dismiss())
                    await choose(str(source))
                    await expect(timeline).to_have_count(3)
                    await export()
                    # An active mock assist must prevent applying or auto-loading a new route.
                    await page.get_by_role('button', name='Start Waypoint Assist').click()
                    await expect(apply).to_be_disabled()
                    count = len(sent)
                    await choose(str(source))
                    await expect(page.locator('.waypoint-card [role=status]')).to_contain_text('Stop Waypoint Assist')
                    assert len(sent) == count
                    await page.get_by_role('button', name='Stop Waypoint Assist').click()
                    await apply.click()
                    await expect(page.locator('.route-state')).to_have_text('Applied to backend')
                    # Invalid files preserve the currently open route.
                    await choose({'name': 'broken.json', 'mimeType': 'application/json', 'buffer': b'{'})
                    await expect(page.locator('.waypoint-card [role=alert]')).to_contain_text('valid JSON')
                    await expect(timeline).to_have_count(2)
                    # Offline preview, edit, download and responsive layout.
                    await stop(backend)
                    await expect(page.locator('#connection-status')).to_contain_text('Disconnected from Python Engine', timeout=10000)
                    await choose(str(source))
                    await expect(page.locator('.waypoint-card [role=status]')).to_contain_text('opened for editing')
                    await page.get_by_role('textbox', name='System', exact=True).fill('Lave')
                    assert (await export())['1']['SystemName'] == 'Lave'
                    await expect(apply).to_be_disabled()
                    screenshot_dir = os.environ.get('EDAP_TEST_SCREENSHOTS')
                    if screenshot_dir:
                        Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
                        await page.locator('.waypoint-card').screenshot(path=str(Path(screenshot_dir) / 'waypoint-editor.png'))
                    await page.set_viewport_size({'width': 390, 'height': 844})
                    await page.locator('.waypoint-card').scroll_into_view_if_needed()
                    assert await page.locator('.waypoint-card').evaluate('(el) => el.scrollWidth <= el.clientWidth')
                    assert await page.locator('.route-workspace').evaluate('(el) => el.scrollWidth <= el.clientWidth')
                    if screenshot_dir:
                        await page.locator('.waypoint-card').screenshot(path=str(Path(screenshot_dir) / 'waypoint-editor-mobile.png'))
                    assert not errors, errors
                    await browser.close()
                    print('PASS: visualize, edit, add/remove/reorder, bookmarks, trading, repeat, validation, undo, download, confirmed apply, active-assist guard, offline editing and mobile layout.')
            except BaseException:
                print(log_path.read_text(), file=sys.stderr)
                raise
            finally:
                await stop(dashboard)
                await stop(backend)
                for command in sent:
                    name = command['filepath']
                    if name.startswith('waypoints/imported-') and Path(name).parent == Path('waypoints'):
                        (ROOT / name).unlink(missing_ok=True)


asyncio.run(main())
