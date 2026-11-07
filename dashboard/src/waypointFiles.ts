import fs from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';
import { parseWaypointRoute, MAX_WAYPOINT_BYTES, WaypointFileError } from './waypointRoute';

export { MAX_WAYPOINT_BYTES, WaypointFileError } from './waypointRoute';

export function importWaypointFile(contents: Buffer, rootDir: string): string {
  if (contents.length > MAX_WAYPOINT_BYTES) throw new WaypointFileError('Waypoint files must be at most 1 MiB.');
  const text = contents.toString('utf8').replace(/^\uFEFF/, '');
  parseWaypointRoute(text);

  // Match Python json.dump's ASCII escaping for the Windows desktop reader.
  // Keep the validated text's ordering; stringifying an object sorts numeric keys.
  const serialized = Buffer.from(text.replace(/[\u007f-\uffff]/g,
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
