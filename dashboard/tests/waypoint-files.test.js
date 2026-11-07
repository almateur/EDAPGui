'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { importWaypointFile, WaypointFileError, MAX_WAYPOINT_BYTES } = require('../dist/waypointFiles');

function checkout(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'edap-waypoints-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.writeFileSync(path.join(root, 'backend_server.py'), '');
  fs.mkdirSync(path.join(root, 'waypoints'));
  return root;
}

test('selected JSON is imported as a unique copy without overwriting a route', t => {
  const root = checkout(t);
  const original = fs.readFileSync(path.join(__dirname, '../../waypoints/waypoints.json'));
  const existing = path.join(root, 'waypoints', 'waypoints.json');
  fs.writeFileSync(existing, original);
  const first = importWaypointFile(original, root);
  const second = importWaypointFile(Buffer.concat([Buffer.from('\uFEFF'), original]), root);
  assert.match(first, /^waypoints\/imported-[a-f0-9-]+\.json$/);
  assert.notEqual(first, second);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root, first))), JSON.parse(original));
  assert.deepEqual(fs.readFileSync(existing), original);
  const localized = JSON.parse(original);
  localized.GlobalShoppingList.Comment = 'München 🛰';
  const unicode = importWaypointFile(Buffer.from(JSON.stringify(localized)), root);
  const serialized = fs.readFileSync(path.join(root, unicode));
  assert.ok(serialized.every(byte => byte < 128));
  assert.deepEqual(JSON.parse(serialized), localized);
});

test('all shipped waypoint examples are valid imports', t => {
  const root = checkout(t);
  const examples = path.resolve(__dirname, '../../waypoints');
  for (const name of fs.readdirSync(examples).filter(name => name.endsWith('.json') && !name.startsWith('imported-'))) {
    const imported = importWaypointFile(fs.readFileSync(path.join(examples, name)), root);
    assert.ok(fs.existsSync(path.join(root, imported)), name);
  }
});

test('invalid, non-waypoint and oversized JSON never creates a file', t => {
  const root = checkout(t);
  for (const contents of ['not JSON', 'null', '[]', '{}', '{"GlobalShoppingList":[]}',
    '{"GlobalShoppingList":{}}', '{"GlobalShoppingList":{"BuyCommodities":{},"UpdateCommodityCount":false,"Skip":true},"bad":{}}']) {
    assert.throws(() => importWaypointFile(Buffer.from(contents), root), WaypointFileError);
  }
  assert.throws(() => importWaypointFile(Buffer.alloc(MAX_WAYPOINT_BYTES + 1), root), WaypointFileError);
  assert.deepEqual(fs.readdirSync(path.join(root, 'waypoints')), []);
});
