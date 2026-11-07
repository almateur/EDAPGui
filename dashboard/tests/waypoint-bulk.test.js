'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { parseWaypointRoute, serializeWaypointRoute, addWaypoint, removeWaypoints, restoreWaypoints, moveWaypoints } = require('../dist/waypointRoute');

function routeWithStops(count) {
  const route = parseWaypointRoute(fs.readFileSync(path.join(__dirname, '../../waypoints/sample-route.json'), 'utf8'));
  route.stops = [];
  for (let i = 1; i <= count; i++) {
    const stop = addWaypoint(route);
    stop.fields.SystemName = `System ${i}`;
  }
  return route;
}
const names = route => route.stops.map(stop => stop.key);

test('bulk removal preserves order and undo keeps edits made to surviving stops', () => {
  const route = routeWithStops(6);
  const second = route.stops[1];
  second.fields.Extension = { untouched: ['custom data'] };
  second.buy.push({ id: 99, name: 'Gold', quantity: 5 });
  const removed = removeWaypoints(route, new Set([second.id, route.stops[2].id, route.stops[5].id]));
  assert.deepEqual(names(route), ['1', '4', '5']);
  route.stops[1].fields.StationName = 'Keep this edit';
  addWaypoint(route).fields.SystemName = 'New stop after removal';
  assert.equal(restoreWaypoints(route, removed), 1);
  assert.deepEqual(route.stops.slice(0, 6).map(stop => stop.fields.SystemName), ['System 1', 'System 2', 'System 3', 'System 4', 'System 5', 'System 6']);
  assert.equal(route.stops[3].fields.StationName, 'Keep this edit');
  assert.equal(route.stops[6].fields.SystemName, 'New stop after removal');
  assert.deepEqual(route.stops[1].fields.Extension, { untouched: ['custom data'] });
  assert.deepEqual(route.stops[1].buy, [{ id: 99, name: 'Gold', quantity: 5 }]);
  assert.equal(route.stops[1].key, '2 (restored)');
  assert.doesNotThrow(() => serializeWaypointRoute(route));
  // Restoring the same records again must not insert duplicates.
  restoreWaypoints(route, removed);
  assert.equal(route.stops.length, 7);
});

test('every combination of removed stops restores the original JSON order and data', () => {
  for (let mask = 0; mask < 256; mask++) {
    const route = routeWithStops(8);
    const original = serializeWaypointRoute(route);
    const ids = new Set(route.stops.filter((_, index) => mask & (1 << index)).map(stop => stop.id));
    const removed = removeWaypoints(route, ids);
    assert.equal(route.stops.length, 8 - ids.size);
    restoreWaypoints(route, removed);
    assert.equal(serializeWaypointRoute(route), original, `selection ${mask}`);
  }
});

test('bulk movement keeps selected blocks and unselected stops in relative order', () => {
  const route = routeWithStops(7);
  const ids = new Set([route.stops[1].id, route.stops[2].id, route.stops[5].id]);
  moveWaypoints(route, ids, -1);
  assert.deepEqual(names(route), ['2', '3', '1', '4', '6', '5', '7']);
  moveWaypoints(route, ids, 1);
  assert.deepEqual(names(route), ['1', '2', '3', '4', '5', '6', '7']);
  const restored = parseWaypointRoute(serializeWaypointRoute(route));
  assert.deepEqual(names(restored), names(route));
  const all = new Set(route.stops.map(stop => stop.id));
  moveWaypoints(route, all, -1);
  moveWaypoints(route, all, 1);
  assert.deepEqual(names(route), ['1', '2', '3', '4', '5', '6', '7']);
});

test('empty routes, unknown selections and single stops are safe no-ops', () => {
  for (const count of [0, 1]) {
    const route = routeWithStops(count);
    const original = serializeWaypointRoute(route);
    const ids = new Set(route.stops.map(stop => stop.id));
    moveWaypoints(route, ids, -1);
    moveWaypoints(route, ids, 1);
    assert.deepEqual(removeWaypoints(route, new Set([-1])), []);
    restoreWaypoints(route, []);
    assert.equal(serializeWaypointRoute(route), original);
  }
});
