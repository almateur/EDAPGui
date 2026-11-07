'use strict';

// This desktop control service trusts local processes, not arbitrary websites
// or LAN clients. Validate Host too, so DNS rebinding cannot bypass Origin checks.
const LOCAL_HOSTS = ['127.0.0.1', 'localhost', '[::1]'];

function createLocalAccess(server) {
  function isAllowed(request, websocket = false) {
    const address = server.address();
    const host = request.headers.host;
    if (!address || typeof address === 'string' || typeof host !== 'string') return false;
    const authority = host.toLowerCase();
    const validHost = LOCAL_HOSTS.some(name =>
      authority === `${name}:${address.port}` || (address.port === 80 && authority === name));
    if (!validHost) return false;

    const origin = request.headers.origin;
    if (origin !== undefined && origin !== `http://${authority}`) return false;
    if (request.headers['sec-fetch-site'] === 'cross-site') return false;
    // Browser WebSockets and state-changing HTTP requests must be same-origin.
    const needsOrigin = websocket || !['GET', 'HEAD', 'OPTIONS'].includes(request.method || 'GET');
    return !needsOrigin || origin === `http://${authority}`;
  }

  function middleware(request, response, next) {
    response.setHeader('X-Content-Type-Options', 'nosniff');
    response.setHeader('Content-Security-Policy', "frame-ancestors 'none'");
    if (!isAllowed(request)) {
      response.status(403).send('Forbidden');
      return;
    }
    next();
  }

  return { isAllowed, middleware };
}

module.exports = { createLocalAccess };
