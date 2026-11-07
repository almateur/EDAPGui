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
exports.MAX_WAYPOINT_BYTES = 1024 * 1024;
class WaypointFileError extends Error {
}
exports.WaypointFileError = WaypointFileError;
function importWaypointFile(contents, rootDir) {
    if (contents.length > exports.MAX_WAYPOINT_BYTES)
        throw new WaypointFileError('Waypoint files must be at most 1 MiB.');
    let data;
    try {
        data = JSON.parse(contents.toString('utf8').replace(/^\uFEFF/, ''));
    }
    catch {
        throw new WaypointFileError('Choose a valid JSON waypoint file.');
    }
    const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
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
    const serialized = Buffer.from(JSON.stringify(data).replace(/[\u007f-\uffff]/g, character => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`));
    if (serialized.length > exports.MAX_WAYPOINT_BYTES)
        throw new WaypointFileError('Waypoint files must be at most 1 MiB.');
    // Resolve the actual backend checkout, including cloud runtime symlinks.
    const sourceRoot = path_1.default.dirname(fs_1.default.realpathSync(path_1.default.join(rootDir, 'backend_server.py')));
    const waypointRoot = fs_1.default.realpathSync(path_1.default.join(sourceRoot, 'waypoints'));
    // The desktop engine saves progress using the route's basename in waypoints/.
    const filename = path_1.default.join(waypointRoot, `imported-${(0, crypto_1.randomUUID)()}.json`);
    fs_1.default.writeFileSync(filename, serialized, { flag: 'wx', mode: 0o600 });
    return path_1.default.relative(sourceRoot, filename).split(path_1.default.sep).join('/');
}
