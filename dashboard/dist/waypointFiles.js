"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.WaypointFileError = exports.MAX_WAYPOINT_BYTES = void 0;
exports.importWaypointFile = importWaypointFile;
const fs_1 = __importDefault(require("fs"));
const path_1 = __importDefault(require("path"));
const crypto_1 = require("crypto");
const waypointRoute_1 = require("./waypointRoute");
var waypointRoute_2 = require("./waypointRoute");
Object.defineProperty(exports, "MAX_WAYPOINT_BYTES", { enumerable: true, get: function () { return waypointRoute_2.MAX_WAYPOINT_BYTES; } });
Object.defineProperty(exports, "WaypointFileError", { enumerable: true, get: function () { return waypointRoute_2.WaypointFileError; } });
function importWaypointFile(contents, rootDir) {
    if (contents.length > waypointRoute_1.MAX_WAYPOINT_BYTES)
        throw new waypointRoute_1.WaypointFileError('Waypoint files must be at most 1 MiB.');
    const text = contents.toString('utf8').replace(/^\uFEFF/, '');
    (0, waypointRoute_1.parseWaypointRoute)(text);
    // Match Python json.dump's ASCII escaping for the Windows desktop reader.
    // Keep the validated text's ordering; stringifying an object sorts numeric keys.
    const serialized = Buffer.from(text.replace(/[\u007f-\uffff]/g, character => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`));
    if (serialized.length > waypointRoute_1.MAX_WAYPOINT_BYTES)
        throw new waypointRoute_1.WaypointFileError('Waypoint files must be at most 1 MiB.');
    // Resolve the actual backend checkout, including cloud runtime symlinks.
    const sourceRoot = path_1.default.dirname(fs_1.default.realpathSync(path_1.default.join(rootDir, 'backend_server.py')));
    const waypointRoot = fs_1.default.realpathSync(path_1.default.join(sourceRoot, 'waypoints'));
    // The desktop engine saves progress using the route's basename in waypoints/.
    const filename = path_1.default.join(waypointRoot, `imported-${(0, crypto_1.randomUUID)()}.json`);
    fs_1.default.writeFileSync(filename, serialized, { flag: 'wx', mode: 0o600 });
    return path_1.default.relative(sourceRoot, filename).split(path_1.default.sep).join('/');
}
