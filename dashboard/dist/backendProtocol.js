"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.supportsWaypointConfirmation = supportsWaypointConfirmation;
const crypto_1 = require("crypto");
const ws_1 = __importDefault(require("ws"));
// Probe before importing a file. An older backend replies to ping but cannot
// acknowledge the load, so retrying the upload would just time out again.
function supportsWaypointConfirmation(engine, timeoutMs = 3000) {
    if (engine.readyState !== ws_1.default.OPEN)
        return Promise.resolve(null);
    return new Promise(resolve => {
        const requestId = `waypoint-capabilities-${(0, crypto_1.randomUUID)()}`;
        let finished = false;
        let legacyPong = false;
        const timer = setTimeout(() => finish(legacyPong ? false : null), timeoutMs);
        function finish(result) {
            if (finished)
                return;
            finished = true;
            clearTimeout(timer);
            engine.off('message', receive);
            engine.off('close', disconnected);
            engine.off('error', disconnected);
            resolve(result);
        }
        function disconnected() { finish(null); }
        function receive(payload) {
            try {
                const message = JSON.parse(payload.toString());
                if (!message || message.type !== 'pong')
                    return;
                // Another browser may ping at the same time. Its uncorrelated pong
                // must not hide a subsequent valid reply to our capability request.
                if (message.request_id === undefined) {
                    if (Array.isArray(message.capabilities) && message.capabilities.includes('waypoint_load_result'))
                        finish(true);
                    else
                        legacyPong = true;
                    return;
                }
                if (message.request_id !== requestId)
                    return;
                finish(Array.isArray(message.capabilities) && message.capabilities.includes('waypoint_load_result'));
            }
            catch { /* Telemetry and malformed replies do not establish support. */ }
        }
        engine.on('message', receive);
        engine.once('close', disconnected);
        engine.once('error', disconnected);
        try {
            engine.send(JSON.stringify({ command: 'ping', request_id: requestId }), error => {
                if (error)
                    finish(null);
            });
        }
        catch {
            finish(null);
        }
    });
}
