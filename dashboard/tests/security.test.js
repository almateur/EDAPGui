'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const path = require('node:path');
const WebSocket = require('ws');

async function freePort() {
  const socket = http.createServer();
  socket.listen(0, '127.0.0.1');
  await once(socket, 'listening');
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  return port;
}

function requestStatus(url, headers = {}, method = 'GET') {
  return new Promise((resolve, reject) => {
    const request = http.request(url, { headers, method }, response => {
      response.resume();
      resolve(response.statusCode);
    });
    request.on('error', reject);
    request.end();
  });
}

for (const entry of ['dist/server.js', 'server.js']) {
  test(`${entry}: local control boundary`, { timeout: 20000 }, async t => {
    const engine = new WebSocket.Server({ host: '127.0.0.1', port: 0 });
    await once(engine, 'listening');
    const commands = [];
    engine.on('connection', ws => ws.on('message', payload => {
      const data = JSON.parse(payload);
      commands.push(data.command);
      if (data.command === 'ping') ws.send(JSON.stringify({ type: 'pong' }));
    }));
    const port = await freePort();
    const origin = `http://127.0.0.1:${port}`;
    const child = spawn(process.execPath, [path.resolve(__dirname, '..', entry)], {
      env: { ...process.env, PORT: String(port), ENGINE_WS_URL: `ws://127.0.0.1:${engine.address().port}` },
      stdio: ['ignore', 'pipe', 'pipe']
    });
    let output = '';
    child.stdout.on('data', x => { output += x; });
    child.stderr.on('data', x => { output += x; });
    t.after(async () => {
      if (child.exitCode === null && child.signalCode === null) {
        const exited = once(child, 'exit');
        child.kill();
        await exited;
      }
      for (const ws of engine.clients) ws.terminate();
      await new Promise(resolve => engine.close(resolve));
    });
    const deadline = Date.now() + 10000;
    while (!output.includes('Connected to Python Engine.')) {
      if (child.exitCode !== null || Date.now() > deadline) throw Error(output);
      await new Promise(resolve => setTimeout(resolve, 25));
    }

    await t.test('health works but forged Host and cross-origin HTTP are denied', async () => {
      assert.equal((await fetch(`${origin}/api/health`)).status, 200);
      for (const headers of [
        { Host: `attacker.example:${port}` },
        { Origin: 'https://attacker.example' },
        { Origin: 'null' },
        { 'Sec-Fetch-Site': 'cross-site' }
      ]) {
        assert.equal(await requestStatus(`${origin}/api/health`, headers), 403, JSON.stringify(headers));
      }
    });

    await t.test('process endpoints reject CSRF before starting work', async () => {
      for (const action of ['build', 'start', 'stop']) {
        for (const headers of [{}, { Origin: 'https://attacker.example' }, { Origin: 'null' }]) {
          assert.equal((await fetch(`${origin}/api/python/${action}`, { method: 'POST', headers })).status,
            403);
        }
      }
      if (entry === 'dist/server.js') {
        const status = await (await fetch(`${origin}/api/python/status`)).json();
        assert.deepEqual(status, { building: false, running: false, pid: null });
        // A same-origin request reaches the handler, which reports no backend to stop.
        assert.equal((await fetch(`${origin}/api/python/stop`, {
          method: 'POST', headers: { Origin: origin }
        })).status, 400);
      }
    });

    await t.test('external links can open the UI but cannot navigate to APIs or frame it', async () => {
      const navigation = {
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Dest': 'document'
      };
      for (const page of ['/', '/index.html', '/?from=link']) {
        assert.equal(await requestStatus(`${origin}${page}`, navigation), 200);
      }
      assert.equal(await requestStatus(`${origin}/api/health`, navigation), 403);
      assert.equal(await requestStatus(`${origin}/api/python/start`, navigation, 'POST'), 403);
      assert.equal(await requestStatus(`${origin}/`, { ...navigation, 'Sec-Fetch-Dest': 'iframe' }), 403);
      assert.equal(await requestStatus(`${origin}/`, { ...navigation, Origin: 'null' }), 403);
      assert.equal(await requestStatus(`${origin}/`, { ...navigation, Host: `attacker.example:${port}` }), 403);
    });

    await t.test('WebSocket rejects foreign/null/missing Origin and forged Host', async () => {
      for (const headers of [
        {}, { Origin: 'https://attacker.example' }, { Origin: 'null' },
        { Origin: origin, Host: `attacker.example:${port}` }
      ]) {
        const ws = new WebSocket(origin.replace('http:', 'ws:'), { headers });
        await assert.rejects(once(ws, 'open'), /401/);
      }
      assert.deepEqual(commands, []);
    });

    await t.test('same-origin clients can relay commands; oversized frames do not crash the server', async () => {
      const ws = new WebSocket(origin.replace('http:', 'ws:'), { origin });
      await once(ws, 'open');
      const received = new Promise(resolve => ws.on('message', payload => {
        const data = JSON.parse(payload);
        if (data.type === 'pong') resolve(data);
      }));
      ws.send(JSON.stringify({ command: 'ping' }));
      const data = await received;
      assert.equal(data.type, 'pong');
      const closed = once(ws, 'close');
      ws.send('x'.repeat(64 * 1024 + 1));
      assert.equal((await closed)[0], 1009);
      assert.equal((await fetch(`${origin}/api/health`)).status, 200);
      assert.deepEqual(commands, ['ping']);
    });
  });
}
