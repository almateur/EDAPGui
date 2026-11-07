'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { parseWaypointRoute, serializeWaypointRoute, addWaypoint, moveWaypoint, newCommodity, WaypointFileError } = require('../dist/waypointRoute');
const sample = () => fs.readFileSync(path.join(__dirname, '../../waypoints/sample-route.json'), 'utf8');

test('reordering numeric names survives serialization and subsequent imports', () => {
  const route = parseWaypointRoute(sample());
  moveWaypoint(route, route.stops[1].id, -1);
  const text = serializeWaypointRoute(route);
  assert.ok(text.indexOf('"2":') < text.indexOf('"1":'));
  const restored = parseWaypointRoute(text);
  assert.deepEqual(restored.stops.map(stop => stop.fields.SystemName), ['Kremainn', 'Eravate']);
  moveWaypoint(restored, restored.stops[0].id, -1);
  moveWaypoint(restored, -1, 1);
  assert.equal(serializeWaypointRoute(restored), text);
});

test('escaped waypoint names, nested JSON and unknown fields are preserved', () => {
  const text = sample().replace('"1":', '"a\\\"b":').replace('"2":', '"c\\u0064":');
  const route = parseWaypointRoute(text);
  assert.deepEqual(route.stops.map(stop => stop.key), ['a"b', 'cd']);
  route.stops[0].fields.Extension = { '1': ['{ "not a key": true }', { nested: 'x' }] };
  route.shopping.fields.FutureOption = false;
  const restored = parseWaypointRoute(serializeWaypointRoute(route));
  assert.deepEqual(restored.stops[0].fields.Extension, route.stops[0].fields.Extension);
  assert.equal(restored.shopping.fields.FutureOption, false);
  assert.deepEqual(restored.stops.map(stop => stop.key), ['a"b', 'cd']);
});

test('add, remove, repeat, field and commodity edits round trip without UI identifiers', () => {
  const route = parseWaypointRoute(sample());
  const repeat = addWaypoint(route, true);
  const stop = addWaypoint(route);
  assert.equal(route.stops.at(-1), repeat);
  stop.fields.SystemName = 'Sol';
  stop.fields.StationName = 'Galileo';
  stop.fields.Comment = 'A custom stop';
  stop.fields.Completed = true;
  stop.fields.FleetCarrierTransfer = true;
  stop.buy.push({ ...newCommodity(), name: 'Gold', quantity: 10 });
  stop.sell.push({ ...newCommodity(), name: 'All', quantity: 0 });
  route.shopping.buy.push({ ...newCommodity(), name: 'Silver', quantity: 5 });
  route.shopping.fields.Skip = false;
  route.stops.splice(0, 1);
  const text = serializeWaypointRoute(route);
  const data = JSON.parse(text);
  assert.equal(data[stop.key].SystemName, 'Sol');
  assert.deepEqual(data[stop.key].BuyCommodities, { Gold: 10 });
  assert.deepEqual(data[stop.key].SellCommodities, { All: 0 });
  assert.deepEqual(data.GlobalShoppingList.BuyCommodities, { Silver: 5 });
  assert.equal(data[stop.key].Completed, true);
  assert.equal(data[stop.key].FleetCarrierTransfer, true);
  assert.equal(data[stop.key].Comment, 'A custom stop');
  assert.equal(data[stop.key].id, undefined);
  assert.equal(parseWaypointRoute(text).stops.at(-1).fields.SystemName, 'REPEAT');
});

test('invalid edits cannot be serialized for apply or download', () => {
  for (const mutate of [
    route => { route.stops[0].key = 'GlobalShoppingList'; },
    route => { route.stops[0].key = route.stops[1].key; },
    route => { route.stops[0].key = ''; },
    route => { route.stops[0].fields.SystemName = ''; },
    route => { route.stops[0].fields.GalaxyBookmarkNumber = 1.5; },
    route => { route.stops[0].fields.Skip = 'false'; },
    route => { route.stops[0].buy.push(newCommodity()); },
    route => { route.stops[0].buy.push({ ...newCommodity(), name: 'Gold', quantity: -1 }); },
    route => { route.stops[0].buy.push({ ...newCommodity(), name: 'Gold', quantity: '' }); },
    route => { route.stops[0].buy.push({ ...newCommodity(), name: 'Gold', quantity: 1 }, { ...newCommodity(), name: 'gold', quantity: 2 }); },
    route => { route.stops[0].fields.SystemName = 'REPEAT'; }
  ]) {
    const route = parseWaypointRoute(sample());
    mutate(route);
    assert.throws(() => serializeWaypointRoute(route), WaypointFileError);
  }
  // The original file contains two root members with the same name. JSON.parse
  // alone discards the first, hiding that a stop was lost.
  assert.throws(() => parseWaypointRoute(sample().replace('"2":', '"1":')), /duplicate names/);
});

test('bookmark-only stops and legacy null comments remain editable', () => {
  const route = parseWaypointRoute(sample());
  route.stops[0].fields.SystemName = '';
  route.stops[0].fields.GalaxyBookmarkNumber = 3;
  route.stops[0].fields.Comment = null;
  const restored = parseWaypointRoute(serializeWaypointRoute(route));
  assert.equal(restored.stops[0].fields.Comment, null);
  assert.equal(restored.stops[0].fields.GalaxyBookmarkNumber, 3);
});
