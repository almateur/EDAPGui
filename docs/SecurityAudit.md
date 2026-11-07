# Security audit and fixes — 7 November 2026

This review covers the dashboard HTTP/WebSocket servers, Python WebSocket engine, network command handlers, waypoint file access, the local EDMesg transport, subprocess launches, model loading, and declared dependencies. It uses source review, live protocol tests, a browser smoke test, npm's advisory database, and the version-specific PyPI vulnerability metadata. It is not a penetration test of a running Windows/game installation.

## Findings addressed

| Finding | Priority | Previous behavior and impact | Fix |
|---------|----------|------------------------------|-----|
| Unauthenticated services exposed beyond the local machine | High | The dashboard listened on all interfaces and the engine defaulted to `0.0.0.0`. A reachable client could control assists, request screenshot streaming, and invoke dashboard process management. | Both services bind to loopback. The engine rejects public bind addresses before initialization. |
| Cross-origin browser control and DNS rebinding | High | Arbitrary webpages could connect to the WebSockets; process-changing HTTP routes had no Origin/Host check. | A shared guard protects both Node entry points, validates Host, and requires same-origin browser WebSockets and state-changing HTTP requests. The engine rejects browser Origin headers, requiring browsers to use the guarded dashboard. |
| Vulnerable JavaScript dependencies | High | `npm audit` reported 14 findings, including 8 high-severity findings, in the dependency graph. | Update Express, `ws`, Vue, Vite, and the associated development tools and lockfile. The regenerated frontend and server include the fixes. The updated audit reports zero findings. |
| Unrestricted network waypoint paths | Medium | A network client could pass an arbitrary filesystem path to the waypoint reader. | Resolve paths before use and require an existing JSON file inside `waypoints/`, at most 1 MiB. Reject traversal, escaping symlinks, non-JSON paths, and oversized files before invoking the loader. |
| Excessive command payloads and connection errors | Medium | Browser WebSocket command limits were much larger than necessary, and protocol errors could become unhandled socket errors. | Limit command messages to 64 KiB, bound the Python receive queue, validate command envelopes, and handle browser socket errors without terminating the service. |
| Published Python dependency advisories | Advisory-dependent | Version-specific PyPI metadata reported advisories for 10 pinned distributions. This is a package match, not proof every vulnerable feature is reachable from this application. | Update the affected pins listed below; update TorchVision with PyTorch and yarl to satisfy aiohttp's dependency constraint. |

## Python dependency changes

| Distribution | Previous pin | Updated pin |
|--------------|--------------|-------------|
| aiohttp | 3.14.1 | 3.14.4 |
| anyio | 4.13.0 | 4.14.2 |
| certifi | 2026.5.20 | 2026.10.18 |
| filelock | 3.29.1 | 4.2.1 |
| fsspec | 2026.4.0 | 2026.6.0 |
| multidict | 6.7.1 | 6.9.1 |
| Pillow | 12.2.0 | 13.0.0 |
| torch | 2.12.0 | 2.13.0 |
| torchvision | 0.27.0 | 0.28.0 |
| ujson | 5.12.1 | 5.13.0 |
| urllib3 | 2.7.0 | 2.8.0 |
| yarl | 1.24.2 | 1.25.1 |

Examples of advisory evidence are [PyTorch GHSA-rrmf-rvhw-rf47](https://github.com/advisories/GHSA-rrmf-rvhw-rf47), [Pillow GHSA-24rc-8hj2-v98c](https://github.com/advisories/GHSA-24rc-8hj2-v98c), and [aiohttp GHSA-mq44-7p77-q5h7](https://github.com/advisories/GHSA-mq44-7p77-q5h7). Version-specific PyPI JSON metadata supplies the affected versions and fixed releases. Advisory aliases were not counted as separate affected packages.

The audit checked all 119 explicitly pinned Python distributions, including environment markers and selected extras when comparing their declared constraints against the Windows CPython 3.11 pins. The updated pinned releases have no published advisories in the checked PyPI metadata. This does not cover every possible transitive resolution of the unpinned requirements or future advisories.

## Validation and limits

- Nine Python tests exercise backend lifecycle, native connectivity, browser-origin rejection, public-bind rejection, oversized commands, and waypoint traversal/symlink handling.
- Twelve Node test-runner checks exercise both the compiled TypeScript server and the legacy JavaScript server: legitimate local requests, external-link navigation to the UI, forged Host and foreign/null/missing Origin, blocked cross-site API/navigation and framing, blocked process changes, forwarded ping/pong, and oversized-frame recovery.
- Client/server builds and Vue type checking pass. Vite now requires Node.js 20.19.x or Node.js 22.12+; its configuration uses the ESM `.mts` extension.
- Chromium validates rendered UI, backend start/stop/restart, five mock assist toggles, stop-all, and forwarded WebSocket ping/pong without browser runtime errors.
- The patched non-ML Python dependencies are installed in a separate validation environment and pass `pip check`. Pillow decodes, converts, and resizes all 46 repository images. PyTorch 2.13.0 and TorchVision 0.28.0 CPU builds pass tensor/native NMS checks; both shipped compass and target models load and complete CPU inference with the repository's Ultralytics version.
- The Windows GUI, PaddleOCR integration, live flight control, native Windows APIs, and live screenshots are not exercised on Linux. Reinstall the full updated requirements in a Windows Python 3.11 environment before treating that workflow as validated.

These are local desktop services, not authenticated remote services. Local processes remain trusted; forwarding either service to another machine is unsupported. Shipped PyTorch models are treated as trusted repository artifacts, not as user-supplied model uploads. No broader guarantee of vulnerability absence is implied by passing these checks.
