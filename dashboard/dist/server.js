"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const express_1 = __importDefault(require("express"));
const http_1 = __importDefault(require("http"));
const path_1 = __importDefault(require("path"));
const ws_1 = __importStar(require("ws"));
const APP_PORT = process.env.PORT || 3000;
const ENGINE_WS_URL = process.env.ENGINE_WS_URL || 'ws://127.0.0.1:8765';
const app = (0, express_1.default)();
const server = http_1.default.createServer(app);
// Serve static compiled Vue frontend assets
const publicPath = path_1.default.join(__dirname, '../dist-client');
const publicPathDev = path_1.default.join(__dirname, '../public');
app.use(express_1.default.static(publicPath));
app.use(express_1.default.static(publicPathDev));
app.use(express_1.default.json());
// API route health check
app.get('/api/health', (_req, res) => {
    res.json({ status: 'ok', engine_url: ENGINE_WS_URL });
});
// WebSocket Server for Dashboard frontend browser clients
const wss = new ws_1.WebSocketServer({ server });
let engineWs = null;
let reconnectTimer = null;
function connectToPythonEngine() {
    console.log(`[Dashboard TS Server] Connecting to Python Engine WebSocket at ${ENGINE_WS_URL}...`);
    engineWs = new ws_1.default(ENGINE_WS_URL);
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
    engineWs.on('message', (data) => {
        try {
            const parsed = JSON.parse(data.toString());
            broadcastToClients(parsed);
        }
        catch (err) {
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
    engineWs.on('error', (err) => {
        console.error('[Dashboard TS Server] Python Engine WS error:', err.message);
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
        if (client.readyState === ws_1.default.OPEN) {
            client.send(msgStr);
        }
    });
}
// Handle browser client connections
wss.on('connection', (ws) => {
    console.log('[Dashboard TS Server] Browser client connected.');
    const isEngineConnected = engineWs !== null && engineWs.readyState === ws_1.default.OPEN;
    const statusMsg = {
        type: 'engine_status',
        connected: isEngineConnected,
        message: isEngineConnected ? 'Connected to EDAP Python Engine' : 'Waiting for Python Engine...'
    };
    ws.send(JSON.stringify(statusMsg));
    ws.on('message', (message) => {
        try {
            const parsed = JSON.parse(message.toString());
            console.log('[Dashboard TS Server] Client command:', parsed);
            if (engineWs && engineWs.readyState === ws_1.default.OPEN) {
                engineWs.send(JSON.stringify(parsed));
            }
            else {
                const errorMsg = {
                    type: 'log',
                    timestamp: new Date().toLocaleTimeString(),
                    message: 'Error: Python Engine is not connected.'
                };
                ws.send(JSON.stringify(errorMsg));
            }
        }
        catch (err) {
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
