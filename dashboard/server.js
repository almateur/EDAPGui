const express = require('express');
const http = require('http');
const path = require('path');
const WebSocket = require('ws');

const APP_PORT = process.env.PORT || 3000;
const ENGINE_WS_URL = process.env.ENGINE_WS_URL || 'ws://127.0.0.1:8765';

const app = express();
const server = http.createServer(app);

// Serve static frontend dashboard assets
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.json());

// API route health check
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', engine_url: ENGINE_WS_URL });
});

// WebSocket Server for Dashboard frontend browser clients
const wss = new WebSocket.Server({ server });

let engineWs = null;
let reconnectTimer = null;

function connectToPythonEngine() {
  console.log(`[Dashboard Server] Connecting to Python Engine WebSocket at ${ENGINE_WS_URL}...`);

  engineWs = new WebSocket(ENGINE_WS_URL);

  engineWs.on('open', () => {
    console.log('[Dashboard Server] Connected to Python Engine.');
    if (reconnectTimer) {
      clearInterval(reconnectTimer);
      reconnectTimer = null;
    }
    // Notify all browser clients
    broadcastToClients({
      type: 'engine_status',
      connected: true,
      message: 'Connected to EDAP Python Engine'
    });
  });

  engineWs.on('message', (data) => {
    try {
      const parsed = JSON.parse(data.toString());
      broadcastToClients(parsed);
    } catch (err) {
      console.error('[Dashboard Server] Error parsing message from Python Engine:', err);
    }
  });

  engineWs.on('close', () => {
    console.log('[Dashboard Server] Disconnected from Python Engine. Retrying in 3s...');
    broadcastToClients({
      type: 'engine_status',
      connected: false,
      message: 'Disconnected from Python Engine'
    });
    scheduleReconnect();
  });

  engineWs.on('error', (err) => {
    console.error('[Dashboard Server] Python Engine WS error:', err.message);
  });
}

function scheduleReconnect() {
  if (!reconnectTimer) {
    reconnectTimer = setInterval(() => {
      connectToPythonEngine();
    }, 3000);
  }
}

function broadcastToClients(msgObj) {
  const msgStr = JSON.stringify(msgObj);
  wss.clients.forEach((client) => {
    if (client.readyState === WebSocket.OPEN) {
      client.send(msgStr);
    }
  });
}

// Handle browser client connections
wss.on('connection', (ws) => {
  console.log('[Dashboard Server] Browser client connected.');

  // Send current engine connection status
  const isEngineConnected = engineWs && engineWs.readyState === WebSocket.OPEN;
  ws.send(JSON.stringify({
    type: 'engine_status',
    connected: isEngineConnected,
    message: isEngineConnected ? 'Connected to EDAP Python Engine' : 'Waiting for Python Engine...'
  }));

  // Relay messages from browser client to Python engine
  ws.on('message', (message) => {
    try {
      const parsed = JSON.parse(message.toString());
      console.log('[Dashboard Server] Client command:', parsed);

      if (engineWs && engineWs.readyState === WebSocket.OPEN) {
        engineWs.send(JSON.stringify(parsed));
      } else {
        ws.send(JSON.stringify({
          type: 'log',
          timestamp: new Date().toLocaleTimeString(),
          message: 'Error: Python Engine is not connected.'
        }));
      }
    } catch (err) {
      console.error('[Dashboard Server] Error forwarding client command:', err);
    }
  });

  ws.on('close', () => {
    console.log('[Dashboard Server] Browser client disconnected.');
  });
});

// Start connecting to Python engine
connectToPythonEngine();

server.listen(APP_PORT, () => {
  console.log(`[Dashboard Server] Dashboard UI running on http://localhost:${APP_PORT}`);
});
