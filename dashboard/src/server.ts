import express, { Request, Response } from 'express';
import http from 'http';
import path from 'path';
import WebSocket, { WebSocketServer } from 'ws';
import { CommandMessage, ServerToClientMessage } from './types';

const APP_PORT = process.env.PORT || 3000;
const ENGINE_WS_URL = process.env.ENGINE_WS_URL || 'ws://127.0.0.1:8765';

const app = express();
const server = http.createServer(app);

// Serve static compiled Vue frontend assets
const publicPath = path.join(__dirname, '../dist-client');
const publicPathDev = path.join(__dirname, '../public');

app.use(express.static(publicPath));
app.use(express.static(publicPathDev));
app.use(express.json());

// API route health check
app.get('/api/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok', engine_url: ENGINE_WS_URL });
});

// WebSocket Server for Dashboard frontend browser clients
const wss = new WebSocketServer({ server });

let engineWs: WebSocket | null = null;
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
  });

  engineWs.on('message', (data: WebSocket.RawData) => {
    try {
      const parsed: ServerToClientMessage = JSON.parse(data.toString());
      broadcastToClients(parsed);
    } catch (err) {
      console.error('[Dashboard TS Server] Error parsing message from Python Engine:', err);
    }
  });

  engineWs.on('close', () => {
    console.log('[Dashboard TS Server] Disconnected from Python Engine. Retrying in 3s...');
    broadcastToClients({
      type: 'engine_status',
      connected: false,
      message: 'Disconnected from Python Engine'
    });
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

  const isEngineConnected = engineWs !== null && engineWs.readyState === WebSocket.OPEN;
  const statusMsg: ServerToClientMessage = {
    type: 'engine_status',
    connected: isEngineConnected,
    message: isEngineConnected ? 'Connected to EDAP Python Engine' : 'Waiting for Python Engine...'
  };
  ws.send(JSON.stringify(statusMsg));

  ws.on('message', (message: WebSocket.RawData) => {
    try {
      const parsed: CommandMessage = JSON.parse(message.toString());
      console.log('[Dashboard TS Server] Client command:', parsed);

      if (engineWs && engineWs.readyState === WebSocket.OPEN) {
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
});

// Start connecting to Python engine
connectToPythonEngine();

server.listen(APP_PORT, () => {
  console.log(`[Dashboard TS Server] Vue.js/TS Dashboard UI running on http://localhost:${APP_PORT}`);
});
