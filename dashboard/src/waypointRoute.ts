// Shared by the browser editor and the import endpoint. Route order is significant
// to Python; Object.entries alone would silently sort numeric waypoint names.
export const MAX_WAYPOINT_BYTES = 1024 * 1024;
export class WaypointFileError extends Error {}

export interface ShoppingFields extends Record<string, unknown> {
  BuyCommodities: Record<string, number>;
  UpdateCommodityCount: boolean;
  Skip: boolean;
  Comment?: string | null;
}
export interface WaypointFields extends ShoppingFields {
  SystemName: string;
  StationName: string;
  GalaxyBookmarkType: string;
  GalaxyBookmarkNumber: number;
  SystemBookmarkType: string;
  SystemBookmarkNumber: number;
  SellCommodities: Record<string, number>;
  FleetCarrierTransfer: boolean;
  Completed: boolean;
}
export interface CommodityDraft { id: number; name: string; quantity: number | string }
export interface StopDraft {
  id: number;
  key: string;
  fields: WaypointFields;
  buy: CommodityDraft[];
  sell: CommodityDraft[];
}
export interface WaypointRoute {
  id: number;
  shopping: { fields: ShoppingFields; buy: CommodityDraft[] };
  stops: StopDraft[];
}
let nextId = 1;
export function newCommodity(): CommodityDraft { return { id: nextId++, name: '', quantity: 0 }; }
const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const fail = (message: string): never => { throw new WaypointFileError(message); };

function validateFields(value: unknown, name: string): void {
  if (!isRecord(value)) fail(`Invalid waypoint entry: ${name}.`);
  const entry = value as Record<string, unknown>;
  for (const field of ['Skip', 'UpdateCommodityCount', ...(name === 'GlobalShoppingList' ? [] : ['Completed', 'FleetCarrierTransfer'])]) {
    if (typeof entry[field] !== 'boolean') fail(`${name}: ${field} must be true or false.`);
  }
  for (const field of ['BuyCommodities', ...(name === 'GlobalShoppingList' ? [] : ['SellCommodities'])]) {
    if (!isRecord(entry[field])) fail(`${name}: ${field} must be a commodity list.`);
    for (const [commodity, quantity] of Object.entries(entry[field] as Record<string, unknown>)) {
      if (!commodity.trim() || typeof quantity !== 'number' || !Number.isSafeInteger(quantity) || quantity < 0) {
        fail(`${name}: commodities need a name and a nonnegative whole quantity.`);
      }
    }
  }
  if (entry.Comment !== undefined && entry.Comment !== null && typeof entry.Comment !== 'string') fail(`${name}: Comment must be text.`);
  if (name === 'GlobalShoppingList') return;
  for (const field of ['SystemName', 'StationName', 'GalaxyBookmarkType', 'SystemBookmarkType']) {
    if (typeof entry[field] !== 'string') fail(`${name}: ${field} must be text.`);
  }
  for (const field of ['GalaxyBookmarkNumber', 'SystemBookmarkNumber']) {
    if (!Number.isSafeInteger(entry[field]) || (entry[field] as number) < -1) fail(`${name}: ${field} must be a whole number of -1 or greater.`);
  }
  if (!entry.Skip && !entry.Completed && !(entry.SystemName as string).trim() && !(entry.StationName as string).trim()
    && (entry.GalaxyBookmarkNumber as number) <= 0 && (entry.SystemBookmarkNumber as number) <= 0) {
    fail(`${name}: enter a system, station, or bookmark, or mark this stop skipped.`);
  }
}

// JSON.parse validates syntax first. This scan only recovers top-level key order,
// including escaped names, without reinterpreting nested values or string content.
function orderedRootKeys(text: string): string[] {
  const keys: string[] = [];
  let depth = 0;
  let expectingKey = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      const start = i++;
      for (; i < text.length; i++) {
        if (text[i] === '\\') i++;
        else if (text[i] === '"') break;
      }
      if (depth === 1 && expectingKey) {
        keys.push(JSON.parse(text.slice(start, i + 1)));
        expectingKey = false;
      }
    } else if (char === '{' || char === '[') {
      depth++;
      if (depth === 1) expectingKey = true;
    } else if (char === '}' || char === ']') depth--;
    else if (char === ',' && depth === 1) expectingKey = true;
  }
  return keys;
}

const commodityRows = (value: Record<string, number>): CommodityDraft[] =>
  Object.entries(value).map(([name, quantity]) => ({ id: nextId++, name, quantity }));

export function parseWaypointRoute(text: string): WaypointRoute {
  if (new TextEncoder().encode(text).length > MAX_WAYPOINT_BYTES) fail('Waypoint files must be at most 1 MiB.');
  text = text.replace(/^\uFEFF/, '');
  let data: unknown;
  try { data = JSON.parse(text); }
  catch { fail('Choose a valid JSON waypoint file.'); }
  if (!isRecord(data) || !isRecord(data.GlobalShoppingList)) fail('Waypoint files must contain a GlobalShoppingList object.');
  const entries = data as Record<string, unknown>;
  const keys = orderedRootKeys(text);
  if (new Set(keys).size !== keys.length) fail('Waypoint names must be unique. The file contains duplicate names.');
  for (const key of keys) validateFields(entries[key], key);
  const shopping = entries.GlobalShoppingList as ShoppingFields;
  const route: WaypointRoute = {
    id: nextId++, shopping: { fields: shopping, buy: commodityRows(shopping.BuyCommodities) },
    stops: keys.filter(key => key !== 'GlobalShoppingList').map(key => {
      const fields = entries[key] as WaypointFields;
      return { id: nextId++, key, fields, buy: commodityRows(fields.BuyCommodities), sell: commodityRows(fields.SellCommodities) };
    })
  };
  serializeWaypointRoute(route);
  return route;
}

function commodities(rows: CommodityDraft[], context: string): Record<string, number> {
  const seen = new Set<string>();
  return Object.fromEntries(rows.map(row => {
    if (!row.name.trim()) fail(`${context}: enter a commodity name or remove the empty row.`);
    if (seen.has(row.name.toLowerCase())) fail(`${context}: duplicate commodity ${row.name}.`);
    seen.add(row.name.toLowerCase());
    if (typeof row.quantity !== 'number' || !Number.isSafeInteger(row.quantity) || row.quantity < 0) fail(`${context}: quantities must be nonnegative whole numbers.`);
    return [row.name, Number(row.quantity)];
  }));
}

export function serializeWaypointRoute(route: WaypointRoute): string {
  const shopping = { ...route.shopping.fields, BuyCommodities: commodities(route.shopping.buy, 'Global shopping list') };
  validateFields(shopping, 'GlobalShoppingList');
  const entries: [string, unknown][] = [['GlobalShoppingList', shopping]];
  const names = new Set(['GlobalShoppingList']);
  route.stops.forEach((stop, index) => {
    if (!stop.key.trim() || names.has(stop.key)) fail('Each stop needs a unique waypoint name other than GlobalShoppingList.');
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
  if (new TextEncoder().encode(json).length > MAX_WAYPOINT_BYTES) fail('Waypoint files must be at most 1 MiB.');
  return json;
}

export function addWaypoint(route: WaypointRoute, repeat = false): StopDraft {
  let number = 1;
  while (route.stops.some(stop => stop.key === String(number))) number++;
  const stop: StopDraft = {
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

export function moveWaypoint(route: WaypointRoute, id: number, offset: number): void {
  const index = route.stops.findIndex(stop => stop.id === id);
  const target = index + offset;
  if (index < 0 || target < 0 || target >= route.stops.length) return;
  const [stop] = route.stops.splice(index, 1);
  route.stops.splice(target, 0, stop);
}

export interface RemovedWaypoint { stop: StopDraft; index: number; nextId: number | null }

export function removeWaypoints(route: WaypointRoute, ids: ReadonlySet<number>): RemovedWaypoint[] {
  const removed: RemovedWaypoint[] = [];
  let nextId: number | null = null;
  for (let index = route.stops.length - 1; index >= 0; index--) {
    const stop = route.stops[index];
    if (ids.has(stop.id)) removed.push({ stop, index, nextId });
    else nextId = stop.id;
  }
  route.stops = route.stops.filter(stop => !ids.has(stop.id));
  return removed.reverse();
}

export function restoreWaypoints(route: WaypointRoute, removed: RemovedWaypoint[]): number {
  const existing = new Set(route.stops.map(stop => stop.id));
  const names = new Set(route.stops.map(stop => stop.key));
  let renamed = 0;
  for (const entry of removed) {
    if (existing.has(entry.stop.id)) continue;
    if (names.has(entry.stop.key)) {
      const original = entry.stop.key;
      let suffix = 1;
      do { entry.stop.key = `${original} (restored${suffix === 1 ? '' : ` ${suffix}`})`; suffix++; }
      while (names.has(entry.stop.key));
      renamed++;
    }
    const anchor = route.stops.findIndex(stop => stop.id === entry.nextId);
    route.stops.splice(anchor >= 0 ? anchor : Math.min(entry.index, route.stops.length), 0, entry.stop);
    existing.add(entry.stop.id);
    names.add(entry.stop.key);
  }
  return renamed;
}

export function moveWaypoints(route: WaypointRoute, ids: ReadonlySet<number>, direction: -1 | 1): void {
  if (route.stops.length < 2 || ids.size === 0) return;
  // Move each selected block one place, preserving both selected and unselected order.
  const start = direction === -1 ? 1 : route.stops.length - 2;
  const end = direction === -1 ? route.stops.length : -1;
  for (let index = start; index !== end; index -= direction) {
    const neighbor = index + direction;
    if (ids.has(route.stops[index].id) && !ids.has(route.stops[neighbor].id)) {
      [route.stops[index], route.stops[neighbor]] = [route.stops[neighbor], route.stops[index]];
    }
  }
}
