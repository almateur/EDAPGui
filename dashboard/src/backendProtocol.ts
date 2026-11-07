import { randomUUID } from 'crypto';
import WebSocket from 'ws';

// Probe before importing a file. An older backend replies to ping but cannot
// acknowledge the load, so retrying the upload would just time out again.
export function supportsWaypointConfirmation(engine: WebSocket, timeoutMs = 3000): Promise<boolean | null> {
  if (engine.readyState !== WebSocket.OPEN) return Promise.resolve(null);
  return new Promise(resolve => {
    const requestId = `waypoint-capabilities-${randomUUID()}`;
    let finished = false;
    let legacyPong = false;
    const timer = setTimeout(() => finish(legacyPong ? false : null), timeoutMs);
    function finish(result: boolean | null): void {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      engine.off('message', receive);
      engine.off('close', disconnected);
      engine.off('error', disconnected);
      resolve(result);
    }
    function disconnected(): void { finish(null); }
    function receive(payload: WebSocket.RawData): void {
      try {
        const message = JSON.parse(payload.toString());
        if (!message || message.type !== 'pong') return;
        // Another browser may ping at the same time. Its uncorrelated pong
        // must not hide a subsequent valid reply to our capability request.
        if (message.request_id === undefined) {
          if (Array.isArray(message.capabilities) && message.capabilities.includes('waypoint_load_result')) finish(true);
          else legacyPong = true;
          return;
        }
        if (message.request_id !== requestId) return;
        finish(Array.isArray(message.capabilities) && message.capabilities.includes('waypoint_load_result'));
      } catch { /* Telemetry and malformed replies do not establish support. */ }
    }
    engine.on('message', receive);
    engine.once('close', disconnected);
    engine.once('error', disconnected);
    try {
      engine.send(JSON.stringify({ command: 'ping', request_id: requestId }), error => {
        if (error) finish(null);
      });
    } catch { finish(null); }
  });
}
