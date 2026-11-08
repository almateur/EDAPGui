import express, { Request, Response, NextFunction } from 'express';
import http from 'http';
import path from 'path';
import fs from 'fs';
import { spawn, ChildProcess } from 'child_process';
import WebSocket, { WebSocketServer } from 'ws';
import { CommandMessage, ProcessStatusMessage, ServerToClientMessage, CalibrationStatusMessage, ShipInfoMessage } from './types';
import { createLocalAccess } from '../security';
import { importWaypointFile, MAX_WAYPOINT_BYTES, WaypointFileError } from './waypointFiles';
import { supportsWaypointConfirmation } from './backendProtocol';

const APP_PORT = process.env.PORT || 3000;
const ENGINE_WS_URL = process.env.ENGINE_WS_URL || 'ws://127.0.0.1:8765';
const ROOT_DIR = path.resolve(__dirname, '../../');

const app = express();
const server = http.createServer(app);
const localAccess = createLocalAccess(server);
app.use(localAccess.middleware);

// Python process state
let isBuildingPython = false;
let pythonBackendProcess: ChildProcess | null = null;

function getPythonExecutable(): string {
  const venvWin = path.join(ROOT_DIR, 'venv', 'Scripts', 'python.exe');
  const venvUnix = path.join(ROOT_DIR, 'venv', 'bin', 'python');

  if (fs.existsSync(venvWin)) return venvWin;
  if (fs.existsSync(venvUnix)) return venvUnix;

  return process.platform === 'win32' ? 'python' : 'python3';
}

function isEngineConnected(): boolean {
  return engineWs !== null && engineWs.readyState === WebSocket.OPEN;
}

function getProcessStatus(extraMessage?: string): ProcessStatusMessage {
  const managed = pythonBackendProcess !== null;
  const connected = isEngineConnected();
  return {
    type: 'process_status',
    building: isBuildingPython,
    running: managed || connected,
    managed,
    connected,
    pid: pythonBackendProcess?.pid,
    message: extraMessage
  };
}

function broadcastProcessStatus(extraMessage?: string): void {
  broadcastToClients(getProcessStatus(extraMessage));
}

function logAndBroadcast(message: string): void {
  const time = new Date().toLocaleTimeString();
  console.log(`[Dashboard TS Server] ${message}`);
  broadcastToClients({
    type: 'log',
    timestamp: time,
    message: message
  });
}

function buildPythonEnvironment(res?: Response): void {
  if (isBuildingPython) {
    const msg = 'Python environment build is already in progress.';
    if (res) res.status(400).json({ error: msg });
    logAndBroadcast(`Warning: ${msg}`);
    return;
  }

  isBuildingPython = true;
  broadcastProcessStatus('Starting Python build and dependency installation...');
  logAndBroadcast('=== Starting Python build & dependency setup ===');

  let command: string;
  let args: string[];

  if (process.platform === 'win32' && fs.existsSync(path.join(ROOT_DIR, 'install_requirements.bat'))) {
    command = 'cmd.exe';
    args = ['/c', 'install_requirements.bat'];
  } else {
    command = getPythonExecutable();
    args = ['-m', 'pip', 'install', '-r', 'requirements.txt'];
  }

  logAndBroadcast(`Executing: ${command} ${args.join(' ')} (in ${ROOT_DIR})`);

  const child = spawn(command, args, { cwd: ROOT_DIR, shell: process.platform === 'win32' });

  child.stdout?.on('data', (data) => {
    const lines = data.toString().split('\n');
    lines.forEach((line: string) => {
      const trimmed = line.trim();
      if (trimmed) logAndBroadcast(`[Python Build] ${trimmed}`);
    });
  });

  child.stderr?.on('data', (data) => {
    const lines = data.toString().split('\n');
    lines.forEach((line: string) => {
      const trimmed = line.trim();
      if (trimmed) logAndBroadcast(`[Python Build Output] ${trimmed}`);
    });
  });

  child.on('error', (err) => {
    isBuildingPython = false;
    logAndBroadcast(`[Python Build Error] Failed to start process: ${err.message}`);
    broadcastProcessStatus(`Build error: ${err.message}`);
  });

  child.on('close', (code) => {
    isBuildingPython = false;
    if (code === 0) {
      logAndBroadcast('=== Python build & dependency setup completed successfully! ===');
      broadcastProcessStatus('Python build completed successfully');
    } else {
      logAndBroadcast(`=== Python build finished with exit code ${code} ===`);
      broadcastProcessStatus(`Python build failed with exit code ${code}`);
    }
  });

  if (res) {
    res.json({ status: 'started', message: 'Python build process initiated.' });
  }
}

function startPythonBackend(res?: Response): void {
  if (pythonBackendProcess || isEngineConnected()) {
    const msg = pythonBackendProcess
      ? 'Python backend server is already running.'
      : 'A backend is already connected and was started outside the dashboard.';
    if (res) res.status(409).json({ error: msg });
    logAndBroadcast(`Warning: ${msg}`);
    broadcastProcessStatus();
    return;
  }

  const pythonExec = getPythonExecutable();
  const scriptPath = path.join(ROOT_DIR, 'backend_server.py');

  logAndBroadcast(`=== Starting Python Backend Server: ${pythonExec} ${scriptPath} ===`);

  try {
    pythonBackendProcess = spawn(pythonExec, [scriptPath], {
      cwd: ROOT_DIR,
      env: { ...process.env, PYTHONUNBUFFERED: '1' }
    });

    const child = pythonBackendProcess;
    broadcastProcessStatus('Python backend server starting...');

    pythonBackendProcess.stdout?.on('data', (data) => {
      const lines = data.toString().split('\n');
      lines.forEach((line: string) => {
        const trimmed = line.trim();
        if (trimmed) logAndBroadcast(`[Python Backend] ${trimmed}`);
      });
    });

    pythonBackendProcess.stderr?.on('data', (data) => {
      const lines = data.toString().split('\n');
      lines.forEach((line: string) => {
        const trimmed = line.trim();
        if (trimmed) logAndBroadcast(`[Python Backend Error] ${trimmed}`);
      });
    });

    pythonBackendProcess.on('error', (err) => {
      logAndBroadcast(`[Python Backend] Failed to launch process: ${err.message}`);
      if (pythonBackendProcess === child) pythonBackendProcess = null;
      broadcastProcessStatus(`Failed to launch backend: ${err.message}`);
    });

    pythonBackendProcess.on('close', (code) => {
      logAndBroadcast(`[Python Backend] Process exited with code ${code}`);
      if (pythonBackendProcess === child) pythonBackendProcess = null;
      broadcastProcessStatus(`Backend process exited with code ${code}`);
    });

    if (res) {
      res.json({ status: 'started', pid: pythonBackendProcess.pid, message: 'Python backend started.' });
    }
  } catch (err: any) {
    logAndBroadcast(`[Python Backend] Error spawning process: ${err.message}`);
    if (res) {
      res.status(500).json({ error: err.message });
    }
  }
}

function stopPythonBackend(res?: Response): void {
  if (!pythonBackendProcess) {
    const external = isEngineConnected();
    const msg = external
      ? 'This backend was started outside the dashboard. Stop it where you launched it.'
      : 'Python backend process is not currently running.';
    if (res) res.status(external ? 409 : 400).json({ error: msg });
    logAndBroadcast(`Warning: ${msg}`);
    return;
  }

  logAndBroadcast('=== Stopping Python Backend Server ===');
  const child = pythonBackendProcess;
  child.kill('SIGTERM');

  // killed only means a signal was sent; wait for close to establish exit.
  const killTimer = setTimeout(() => {
    if (child.exitCode === null && child.signalCode === null) {
      logAndBroadcast('Force killing Python Backend Server...');
      child.kill('SIGKILL');
    }
  }, 1000);
  child.once('close', () => {
    clearTimeout(killTimer);
    if (res) res.json({ status: 'stopped', message: 'Python backend stopped.' });
  });
}

// Serve static compiled Vue frontend assets
const publicPath = path.join(__dirname, '../dist-client');
const publicPathDev = path.join(__dirname, '../public');

app.use(express.static(publicPath));
app.use(express.static(publicPathDev));

app.post('/api/waypoints/import', async (_req: Request, res: Response, next: NextFunction) => {
  const backend = engineWs;
  if (!backend || backend.readyState !== WebSocket.OPEN) {
    res.status(503).json({ error: 'Connect the Python backend before loading a waypoint file.' });
    return;
  }
  const compatible = await supportsWaypointConfirmation(backend);
  if (compatible === null) {
    res.status(503).json({ error: 'The Python backend is not responding. Check its terminal and restart it before loading a file.' });
    return;
  }
  if (!compatible) {
    res.status(409).json({ error: 'The connected Python backend is outdated. Stop it with Ctrl+C and restart backend_server.py from the updated checkout, then retry.' });
    return;
  }
  next();
}, express.raw({ type: 'application/json', limit: MAX_WAYPOINT_BYTES, inflate: false }),
(req: Request, res: Response) => {
  if (!Buffer.isBuffer(req.body)) {
    res.status(415).json({ error: 'Waypoint files must be sent as application/json.' });
    return;
  }
  try {
    res.status(201).json({ filepath: importWaypointFile(req.body, ROOT_DIR) });
  } catch (error) {
    if (error instanceof WaypointFileError) res.status(400).json({ error: error.message });
    else {
      console.error('[Dashboard TS Server] Waypoint import failed:', error);
      res.status(500).json({ error: 'Unable to save the imported waypoint file.' });
    }
  }
}, (error: { type?: string }, _req: Request, res: Response, _next: NextFunction) => {
  res.status(error.type === 'entity.too.large' ? 413 : 400)
    .json({ error: error.type === 'entity.too.large' ? 'Waypoint files must be at most 1 MiB.' : 'Unable to read the waypoint file.' });
});
app.use(express.json());

// API route health check
app.get('/api/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok', engine_url: ENGINE_WS_URL });
});

// Process management REST endpoints
app.get('/api/python/status', (_req: Request, res: Response) => {
  const status = getProcessStatus();
  res.json({
    building: status.building,
    running: status.running,
    managed: status.managed,
    connected: status.connected,
    pid: status.pid ?? null
  });
});

app.post('/api/python/build', (_req: Request, res: Response) => {
  buildPythonEnvironment(res);
});

app.post('/api/python/start', (_req: Request, res: Response) => {
  startPythonBackend(res);
});

app.post('/api/python/stop', (_req: Request, res: Response) => {
  stopPythonBackend(res);
});

// WebSocket Server for Dashboard frontend browser clients
const wss = new WebSocketServer({
  server,
  maxPayload: 64 * 1024,
  verifyClient: (info: { req: http.IncomingMessage }) => localAccess.isAllowed(info.req, true)
});

let engineWs: WebSocket | null = null;
let calibrationStatus: CalibrationStatusMessage | null = null;
let shipInfo: ShipInfoMessage | null = null;
let reconnectTimer: NodeJS.Timeout | null = null;

function connectToPythonEngine(): void {
  console.log(`[Dashboard TS Server] Connecting to Python Engine WebSocket at ${ENGINE_WS_URL}...`);

  engineWs = new WebSocket(ENGINE_WS_URL);

  engineWs.on('open', () => {
    console.log('[Dashboard TS Server] Connected to Python Engine.');
    if (reconnectTimer) {
      clearInterval(reconnectTimer);
      reconnectTimer = null;
    }
    broadcastToClients({
      type: 'engine_status',
      connected: true,
      message: 'Connected to EDAP Python Engine'
    });
    broadcastProcessStatus();
  });

  engineWs.on('message', (data: WebSocket.RawData) => {
    try {
      const parsed: ServerToClientMessage = JSON.parse(data.toString());
      if (parsed.type === 'calibration_status') calibrationStatus = parsed;
      if (parsed.type === 'ship_info') shipInfo = parsed;
      broadcastToClients(parsed);
    } catch (err) {
      console.error('[Dashboard TS Server] Error parsing message from Python Engine:', err);
    }
  });

  engineWs.on('close', () => {
    calibrationStatus = null;
    shipInfo = null;
    console.log('[Dashboard TS Server] Disconnected from Python Engine. Retrying in 3s...');
    broadcastToClients({
      type: 'engine_status',
      connected: false,
      message: 'Disconnected from Python Engine'
    });
    broadcastProcessStatus();
    scheduleReconnect();
  });

  engineWs.on('error', (err: Error) => {
    console.error('[Dashboard TS Server] Python Engine WS error:', err.message);
  });
}

function scheduleReconnect(): void {
  if (!reconnectTimer) {
    reconnectTimer = setInterval(() => {
      connectToPythonEngine();
    }, 3000);
  }
}

function broadcastToClients(msgObj: ServerToClientMessage): void {
  const msgStr = JSON.stringify(msgObj);
  wss.clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(msgStr);
    }
  });
}

// Handle browser client connections
wss.on('connection', (ws: WebSocket) => {
  console.log('[Dashboard TS Server] Browser client connected.');

  const connected = isEngineConnected();
  const statusMsg: ServerToClientMessage = {
    type: 'engine_status',
    connected,
    message: connected ? 'Connected to EDAP Python Engine' : 'Waiting for Python Engine...'
  };
  ws.send(JSON.stringify(statusMsg));
  ws.send(JSON.stringify(getProcessStatus()));
  if (connected && calibrationStatus) ws.send(JSON.stringify(calibrationStatus));
  if (connected && shipInfo) ws.send(JSON.stringify(shipInfo));

  ws.on('message', (message: WebSocket.RawData) => {
    try {
      const parsed: CommandMessage = JSON.parse(message.toString());
      if (!parsed || Array.isArray(parsed) || typeof parsed.command !== 'string') {
        throw new Error('Command must be a JSON object with a command string');
      }
      console.log('[Dashboard TS Server] Client command:', parsed.command);

      if (parsed.command === 'build_python') {
        buildPythonEnvironment();
      } else if (parsed.command === 'start_python_backend') {
        startPythonBackend();
      } else if (parsed.command === 'stop_python_backend') {
        stopPythonBackend();
      } else if (engineWs && engineWs.readyState === WebSocket.OPEN) {
        engineWs.send(JSON.stringify(parsed));
      } else {
        const errorMsg: ServerToClientMessage = {
          type: 'log',
          timestamp: new Date().toLocaleTimeString(),
          message: 'Error: Python Engine is not connected.'
        };
        ws.send(JSON.stringify(errorMsg));
      }
    } catch (err) {
      console.error('[Dashboard TS Server] Error forwarding client command:', err);
    }
  });

  ws.on('close', () => {
    console.log('[Dashboard TS Server] Browser client disconnected.');
  });
  ws.on('error', (err: Error) => {
    console.warn('[Dashboard TS Server] Browser WebSocket error:', err.message);
  });
});

// Start connecting to Python engine
connectToPythonEngine();

server.listen(Number(APP_PORT), '127.0.0.1', () => {
  console.log(`[Dashboard TS Server] Vue.js/TS Dashboard UI running on http://localhost:${APP_PORT}`);
});
