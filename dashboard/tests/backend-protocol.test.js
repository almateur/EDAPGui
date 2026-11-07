'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { once } = require('node:events');
const WebSocket = require('ws');
const { supportsWaypointConfirmation } = require('../dist/backendProtocol');

for (const mode of ['supported', 'legacy', 'silent']) {
  test(`backend capability probe: ${mode}`, async t => {
    const server = new WebSocket.Server({ host: '127.0.0.1', port: 0 });
    await once(server, 'listening');
    server.on('connection', peer => peer.on('message', payload => {
      const request = JSON.parse(payload);
      assert.equal(request.command, 'ping');
      if (mode === 'supported') {
        peer.send(JSON.stringify({ type: 'pong' }));
        peer.send('not JSON');
        peer.send(JSON.stringify({ type: 'pong', request_id: 'wrong-request', capabilities: [] }));
        peer.send(JSON.stringify({ type: 'pong', request_id: request.request_id, capabilities: ['waypoint_load_result'] }));
      } else if (mode === 'legacy') peer.send(JSON.stringify({ type: 'pong' }));
    }));
    const client = new WebSocket(`ws://127.0.0.1:${server.address().port}`);
    t.after(async () => {
      client.terminate();
      for (const peer of server.clients) peer.terminate();
      await new Promise(resolve => server.close(resolve));
    });
    await once(client, 'open');
    const listeners = client.listenerCount('message');
    assert.equal(await supportsWaypointConfirmation(client, 100), mode === 'supported' ? true : mode === 'legacy' ? false : null);
    assert.equal(client.listenerCount('message'), listeners);
  });
}
