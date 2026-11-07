import fs from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';

export const MAX_WAYPOINT_BYTES = 1024 * 1024;
export class WaypointFileError extends Error {}

export function importWaypointFile(contents: Buffer, rootDir: string): string {
  if (contents.length > MAX_WAYPOINT_BYTES) throw new WaypointFileError('Waypoint files must be at most 1 MiB.');
  let data: unknown;
  try {
    data = JSON.parse(contents.toString('utf8').replace(/^\uFEFF/, ''));
  } catch {
    throw new WaypointFileError('Choose a valid JSON waypoint file.');
  }
  const isRecord = (value: unknown): value is Record<string, unknown> =>
    value !== null && typeof value === 'object' && !Array.isArray(value);
  if (!isRecord(data) || !isRecord(data.GlobalShoppingList)) {
    throw new WaypointFileError('Waypoint files must contain a GlobalShoppingList object.');
  }
  const waypointFields = ['SystemName', 'StationName', 'GalaxyBookmarkType', 'GalaxyBookmarkNumber',
    'SystemBookmarkType', 'SystemBookmarkNumber', 'SellCommodities', 'BuyCommodities',
    'UpdateCommodityCount', 'FleetCarrierTransfer', 'Skip', 'Completed'];
  for (const [name, entry] of Object.entries(data)) {
    const required = name === 'GlobalShoppingList' ? ['BuyCommodities', 'UpdateCommodityCount', 'Skip'] : waypointFields;
    if (!isRecord(entry) || required.some(field => !Object.prototype.hasOwnProperty.call(entry, field))) {
      throw new WaypointFileError(`Invalid waypoint entry: ${name}.`);
    }
  }

  // Match Python json.dump's ASCII escaping for the Windows desktop reader.
  const serialized = Buffer.from(JSON.stringify(data).replace(/[\u007f-\uffff]/g,
    character => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`));
  if (serialized.length > MAX_WAYPOINT_BYTES) throw new WaypointFileError('Waypoint files must be at most 1 MiB.');

  // Resolve the actual backend checkout, including cloud runtime symlinks.
  const sourceRoot = path.dirname(fs.realpathSync(path.join(rootDir, 'backend_server.py')));
  const waypointRoot = fs.realpathSync(path.join(sourceRoot, 'waypoints'));
  // The desktop engine saves progress using the route's basename in waypoints/.
  const filename = path.join(waypointRoot, `imported-${randomUUID()}.json`);
  fs.writeFileSync(filename, serialized, { flag: 'wx', mode: 0o600 });
  return path.relative(sourceRoot, filename).split(path.sep).join('/');
}
