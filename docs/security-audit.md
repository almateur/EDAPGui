# EDAPGui security audit

Date: 7 November 2026. Reviewed commit: `73a574338beac098e14365761cecc9759217892d` on `fix/backend-websocket-process-lifecycle`.

The dashboard and backend have significant security gaps. Prioritize authentication, browser request validation, and WebSocket error handling before exposing either service to untrusted clients. The previous lifecycle fixes do not address these security boundaries.

## Scope and method

Reviewed the Python WebSocket backend, TypeScript dashboard server and Vue client, legacy dashboard server/client, waypoint loader, EDMesg transport, startup scripts, and dependency declarations. Used local mock services and an isolated Node child process for dynamic checks; no game controls, real screenshots, sensitive files, or external targets were exercised. Audited the npm lockfile and 119 exact Python requirements pins against the available package advisory services.

No application source or dependency files were modified. This is a focused audit, not a complete assessment of Windows APIs, OCR/model parsing, every dependency's exploitability, or deployed firewall/reverse-proxy configuration.

## Findings

### 1. High — Unauthenticated network control and screen-stream access

Locations: `dashboard/src/server.ts:223`, `dashboard/src/server.ts:301`, `dashboard/src/server.ts:346`; `backend_server.py:32`, `backend_server.py:174`, `backend_server.py:254`, `backend_server.py:294`.

The dashboard listens without a host restriction, and the Python backend defaults to `0.0.0.0`. Neither service authenticates clients. Anyone who can reach the relevant port can invoke available assist commands; the dashboard also exposes dependency installation and backend start/stop through REST and WebSocket commands. A direct backend connection bypasses any protection added solely to the dashboard.

The debug stream can be enabled by any client and its frames are broadcast to all connected clients. On a live Windows installation, this exposes screenshots of the screen region captured by the autopilot, alongside telemetry and logs. Actual screen capture was not exercised in this environment.

Evidence: an unauthenticated backend connection successfully changed `debug_stream_active`. An unauthenticated dashboard connection successfully relayed the same command to an isolated backend.

Remediation: bind both services to loopback by default; authenticate REST requests and WebSocket handshakes at both layers; authorize process-management, control, and screen-stream operations. Require explicit configuration and TLS for remote use. Remove or separately restrict the web-accessible dependency installer. Loopback binding alone does not fix finding 2.

### 2. High — Missing Origin/CSRF validation permits browser-mediated commands

Locations: `dashboard/src/server.ts:223`, `dashboard/src/server.ts:236`; `backend_server.py:294`.

Both WebSocket servers accept an arbitrary `Origin`. The state-changing REST handlers do not validate Origin or require a CSRF token. They also accept a POST with `Content-Type: text/plain` and an empty body. Because authentication is absent, malicious pages can attempt commands against a reachable installation without possessing a session. CORS response restrictions alone do not prevent these writes or replace WebSocket Origin checks.

Evidence: connections specifying `Origin: https://untrusted.example` were accepted by both services and changed mock backend state. A simple cross-origin-style POST reached the dashboard stop handler and returned its application-level “not currently running” response rather than an authorization rejection.

This verifies the server-side acceptance condition using a protocol client. A real-browser exploit was not executed; browser mixed-content and local/private-network protections may affect reachability.

Remediation: enforce an exact trusted-Origin allowlist for browser WebSocket handshakes and state-changing HTTP requests, with a deliberate authenticated policy for non-browser clients. Add authentication and CSRF protection where applicable. Do not use wildcard Origins or rely on browser network restrictions.

### 3. High — One malformed WebSocket frame terminates the dashboard

Location: `dashboard/src/server.ts:301`.

Accepted browser sockets have message and close listeners but no error listener. Protocol parsing errors are emitted on the socket asynchronously, outside the message callback's try/catch. An unhandled EventEmitter error terminates Node and disconnects all dashboard clients.

Evidence: completed a WebSocket upgrade against an isolated dashboard process, then sent one short unmasked text frame. Node exited with status 1 and `WS_ERR_EXPECTED_MASK`. This did not terminate the development dashboard or interact with the game. The legacy `dashboard/server.js` follows the same missing-error-handler pattern, but was not independently reproduced.

Remediation: register per-client socket error handlers and close only the offending connection. Set suitable payload/connection/rate limits. Add a regression that sends an invalid frame and verifies another client can still use the server. Updating `ws` alone does not replace application error handling.

### 4. High — Dependencies with published security advisories

Locations: `dashboard/package.json:14`, `dashboard/package-lock.json`, `requirements.txt`.

`npm audit --json` reports **14 affected package entries: 8 high and 6 moderate**. Counts include transitive packages and propagated findings, not 14 distinct demonstrated vulnerabilities.

- Production `ws` 8.17.1: memory-disclosure advisory [GHSA-58qx-3vcg-4xpx](https://github.com/advisories/GHSA-58qx-3vcg-4xpx), patched in 8.20.1, and memory-exhaustion advisory [GHSA-96hv-2xvq-fx4p](https://github.com/advisories/GHSA-96hv-2xvq-fx4p), patched in 8.21.0. These are distinct from finding 3.
- Express's dependency tree includes body-parser DoS and path-to-regexp/qs advisories. The current routes do not establish exploitability of every flagged feature; for example, qs.stringify and complex route-pattern advisories need their respective APIs to be used.
- Development Vite 5.2.14 has file-access and cross-origin advisories, including [GHSA-vg6x-rcgg-rjx6](https://github.com/advisories/GHSA-vg6x-rcgg-rjx6). Vite findings concern the development server; the production Express server does not run Vite.
- Vue's tree includes an SSR-related advisory. The reviewed dashboard uses client-side rendering, so this audit did not establish an active SSR exploit path.

`pip-audit` completed against **119 pinned requirements**, reporting **99 advisory entries across 10 packages**, representing 82 distinct `(package, advisory ID)` pairs. Affected packages: aiohttp 3.14.1, anyio 4.13.0, certifi 2026.5.20, filelock 3.29.1, fsspec 2026.4.0, multidict 6.7.1, pillow 12.2.0, torch 2.12.0, ujson 5.12.1, urllib3 2.7.0. These are advisory-service matches; individual Python exploit paths were not verified. Duplicate IDs and possible aliases mean these numbers must not be presented as unique exploitable CVEs.

The unpinned `websockets>=12.0` requirement was excluded from the exact-pin scan. A separate scan of the installed mock runtime found no advisories for websockets 15.0.1; it did flag the environment's pip 25.0.1 (12 advisory entries). pip is tooling, not the running backend's network handler.

Remediation: upgrade to supported patched releases, refresh the lockfile intentionally, rebuild the tracked distribution outputs when shipping, and rerun the audits and application tests. Audit the Windows environment after resolving/installing its complete dependency graph. Do not blindly run a forced dependency update or interpret a scanner's lack of an automatic fix as proof no upstream fix exists.

### 5. Medium — Remote waypoint filenames cross the filesystem boundary

Locations: `backend_server.py:248`, `EDWayPoint.py:58`, `EDWayPoint.py:83`; also `EDAP_EDMesg_Server.py:100`.

Remote commands pass the supplied filepath directly to the waypoint loader without restricting its root, absolute paths, parent traversal, network paths, or file size. The loader checks existence and reads JSON from that path. On Windows, a UNC path can cause outbound SMB access and potentially credential negotiation, subject to OS/network policy. Large files or special files can also block the synchronous event loop or consume resources.

Evidence: a stub loader received `../outside-route.json` unchanged. Source inspection confirms the downstream filesystem calls. No real out-of-directory file was read, no UNC request was attempted, and credential disclosure was not demonstrated. This is not a demonstrated arbitrary-file exfiltration or arbitrary-file-write vulnerability.

Remediation: restrict network-supplied selections to a configured waypoint directory, resolve paths and enforce containment including symlinks, reject UNC/device paths, limit file size, and validate the waypoint schema. Keep any broader trusted desktop file-picker workflow separate from network command permissions.

## Verification evidence

Local checks used an isolated mock backend and a temporary dashboard child process on loopback ports:

1. Connect to each WebSocket service without credentials and with an untrusted Origin; send a debug-stream toggle and verify mock state changes.
2. Send an empty `text/plain` POST with the same Origin to the process stop endpoint; verify it reaches the application handler.
3. Upgrade a WebSocket connection to the isolated dashboard, send one unmasked text frame, and verify the process exits with `WS_ERR_EXPECTED_MASK`.
4. Pass a parent-directory waypoint path to a stub loader; verify it is forwarded unchanged without reading a real file.

The raw advisory reports and local probe script are retained in the audit workspace under `/workspace/edap-runtime/`; they are not part of this repository. npm checks used `npm audit --json`. Python checks used pip-audit against the exact pins, without resolving or installing the Windows application requirements.

Recommended order: close unauthenticated access and browser request paths, fix socket errors, upgrade vulnerable dependencies with compatibility checks, then constrain remote file selection. No security remediation has been applied by this audit.
