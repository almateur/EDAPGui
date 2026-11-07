"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.WaypointFileError = exports.MAX_WAYPOINT_BYTES = void 0;
exports.newCommodity = newCommodity;
exports.parseWaypointRoute = parseWaypointRoute;
exports.serializeWaypointRoute = serializeWaypointRoute;
exports.addWaypoint = addWaypoint;
exports.moveWaypoint = moveWaypoint;
// Shared by the browser editor and the import endpoint. Route order is significant
// to Python; Object.entries alone would silently sort numeric waypoint names.
exports.MAX_WAYPOINT_BYTES = 1024 * 1024;
class WaypointFileError extends Error {
}
exports.WaypointFileError = WaypointFileError;
let nextId = 1;
function newCommodity() { return { id: nextId++, name: '', quantity: 0 }; }
const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const fail = (message) => { throw new WaypointFileError(message); };
function validateFields(value, name) {
    if (!isRecord(value))
        fail(`Invalid waypoint entry: ${name}.`);
    const entry = value;
    for (const field of ['Skip', 'UpdateCommodityCount', ...(name === 'GlobalShoppingList' ? [] : ['Completed', 'FleetCarrierTransfer'])]) {
        if (typeof entry[field] !== 'boolean')
            fail(`${name}: ${field} must be true or false.`);
    }
    for (const field of ['BuyCommodities', ...(name === 'GlobalShoppingList' ? [] : ['SellCommodities'])]) {
        if (!isRecord(entry[field]))
            fail(`${name}: ${field} must be a commodity list.`);
        for (const [commodity, quantity] of Object.entries(entry[field])) {
            if (!commodity.trim() || typeof quantity !== 'number' || !Number.isSafeInteger(quantity) || quantity < 0) {
                fail(`${name}: commodities need a name and a nonnegative whole quantity.`);
            }
        }
    }
    if (entry.Comment !== undefined && entry.Comment !== null && typeof entry.Comment !== 'string')
        fail(`${name}: Comment must be text.`);
    if (name === 'GlobalShoppingList')
        return;
    for (const field of ['SystemName', 'StationName', 'GalaxyBookmarkType', 'SystemBookmarkType']) {
        if (typeof entry[field] !== 'string')
            fail(`${name}: ${field} must be text.`);
    }
    for (const field of ['GalaxyBookmarkNumber', 'SystemBookmarkNumber']) {
        if (!Number.isSafeInteger(entry[field]) || entry[field] < -1)
            fail(`${name}: ${field} must be a whole number of -1 or greater.`);
    }
    if (!entry.Skip && !entry.Completed && !entry.SystemName.trim() && !entry.StationName.trim()
        && entry.GalaxyBookmarkNumber <= 0 && entry.SystemBookmarkNumber <= 0) {
        fail(`${name}: enter a system, station, or bookmark, or mark this stop skipped.`);
    }
}
// JSON.parse validates syntax first. This scan only recovers top-level key order,
// including escaped names, without reinterpreting nested values or string content.
function orderedRootKeys(text) {
    const keys = [];
    let depth = 0;
    let expectingKey = false;
    for (let i = 0; i < text.length; i++) {
        const char = text[i];
        if (char === '"') {
            const start = i++;
            for (; i < text.length; i++) {
                if (text[i] === '\\')
                    i++;
                else if (text[i] === '"')
                    break;
            }
            if (depth === 1 && expectingKey) {
                keys.push(JSON.parse(text.slice(start, i + 1)));
                expectingKey = false;
            }
        }
        else if (char === '{' || char === '[') {
            depth++;
            if (depth === 1)
                expectingKey = true;
        }
        else if (char === '}' || char === ']')
            depth--;
        else if (char === ',' && depth === 1)
            expectingKey = true;
    }
    return keys;
}
const commodityRows = (value) => Object.entries(value).map(([name, quantity]) => ({ id: nextId++, name, quantity }));
function parseWaypointRoute(text) {
    if (new TextEncoder().encode(text).length > exports.MAX_WAYPOINT_BYTES)
        fail('Waypoint files must be at most 1 MiB.');
    text = text.replace(/^\uFEFF/, '');
    let data;
    try {
        data = JSON.parse(text);
    }
    catch {
        fail('Choose a valid JSON waypoint file.');
    }
    if (!isRecord(data) || !isRecord(data.GlobalShoppingList))
        fail('Waypoint files must contain a GlobalShoppingList object.');
    const entries = data;
    const keys = orderedRootKeys(text);
    if (new Set(keys).size !== keys.length)
        fail('Waypoint names must be unique. The file contains duplicate names.');
    for (const key of keys)
        validateFields(entries[key], key);
    const shopping = entries.GlobalShoppingList;
    const route = {
        id: nextId++, shopping: { fields: shopping, buy: commodityRows(shopping.BuyCommodities) },
        stops: keys.filter(key => key !== 'GlobalShoppingList').map(key => {
            const fields = entries[key];
            return { id: nextId++, key, fields, buy: commodityRows(fields.BuyCommodities), sell: commodityRows(fields.SellCommodities) };
        })
    };
    serializeWaypointRoute(route);
    return route;
}
function commodities(rows, context) {
    const seen = new Set();
    return Object.fromEntries(rows.map(row => {
        if (!row.name.trim())
            fail(`${context}: enter a commodity name or remove the empty row.`);
        if (seen.has(row.name.toLowerCase()))
            fail(`${context}: duplicate commodity ${row.name}.`);
        seen.add(row.name.toLowerCase());
        if (typeof row.quantity !== 'number' || !Number.isSafeInteger(row.quantity) || row.quantity < 0)
            fail(`${context}: quantities must be nonnegative whole numbers.`);
        return [row.name, Number(row.quantity)];
    }));
}
function serializeWaypointRoute(route) {
    const shopping = { ...route.shopping.fields, BuyCommodities: commodities(route.shopping.buy, 'Global shopping list') };
    validateFields(shopping, 'GlobalShoppingList');
    const entries = [['GlobalShoppingList', shopping]];
    const names = new Set(['GlobalShoppingList']);
    route.stops.forEach((stop, index) => {
        if (!stop.key.trim() || names.has(stop.key))
            fail('Each stop needs a unique waypoint name other than GlobalShoppingList.');
        names.add(stop.key);
        const fields = { ...stop.fields, BuyCommodities: commodities(stop.buy, stop.key), SellCommodities: commodities(stop.sell, stop.key) };
        validateFields(fields, stop.key);
        if (!fields.Skip && fields.SystemName.trim().toUpperCase() === 'REPEAT' && index !== route.stops.length - 1) {
            fail('Move the REPEAT stop to the end of the route, or skip it.');
        }
        entries.push([stop.key, fields]);
    });
    // Emit each entry separately so JS cannot reorder integer-like waypoint names.
    const json = '{\n' + entries.map(([key, value]) => `  ${JSON.stringify(key)}: ${JSON.stringify(value, null, 2).replace(/\n/g, '\n  ')}`).join(',\n') + '\n}\n';
    if (new TextEncoder().encode(json).length > exports.MAX_WAYPOINT_BYTES)
        fail('Waypoint files must be at most 1 MiB.');
    return json;
}
function addWaypoint(route, repeat = false) {
    let number = 1;
    while (route.stops.some(stop => stop.key === String(number)))
        number++;
    const stop = {
        id: nextId++, key: String(number), buy: [], sell: [], fields: {
            SystemName: repeat ? 'REPEAT' : '', StationName: '', GalaxyBookmarkType: '', GalaxyBookmarkNumber: 0,
            SystemBookmarkType: '', SystemBookmarkNumber: 0, SellCommodities: {}, BuyCommodities: {}, Comment: '',
            UpdateCommodityCount: false, FleetCarrierTransfer: false, Skip: false, Completed: false
        }
    };
    const repeatIndex = route.stops.findIndex(item => item.fields.SystemName.trim().toUpperCase() === 'REPEAT');
    route.stops.splice(!repeat && repeatIndex >= 0 ? repeatIndex : route.stops.length, 0, stop);
    return stop;
}
function moveWaypoint(route, id, offset) {
    const index = route.stops.findIndex(stop => stop.id === id);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= route.stops.length)
        return;
    const [stop] = route.stops.splice(index, 1);
    route.stops.splice(target, 0, stop);
}
