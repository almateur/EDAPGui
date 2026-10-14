<script setup lang="ts">
import { ref, reactive, onMounted, computed, nextTick } from 'vue';
import type { TelemetryData, ServerToClientMessage, CommandMessage } from './types';

// Reactive state
const isConnected = ref(false);
const statusMessage = ref('Connecting to Engine...');
const debugStreamActive = ref(false);
const debugImageSrc = ref('');
const waypointFilepath = ref('waypoints/route.json');
const logConsole = ref<HTMLElement | null>(null);

const telemetry = reactive<TelemetryData>({
  status: 'Idle',
  system: 'Unknown',
  ship: 'Unknown',
  fuel: 100,
  jump_info: 'Dist: 0ly Jumps: 0/0',
  assists: {
    fsd: false,
    sc: false,
    waypoint: false,
    robigo: false,
    dss: false,
    single_waypoint: false,
    afk_combat: false
  }
});

interface LogEntry {
  id: number;
  timestamp: string;
  message: string;
  isSystem?: boolean;
}

const logs = ref<LogEntry[]>([
  { id: 1, timestamp: new Date().toLocaleTimeString(), message: 'Connected to EDAP Vue.js + TypeScript Dashboard UI', isSystem: true }
]);

let ws: WebSocket | null = null;
let logIdCounter = 2;

const roundedFuel = computed(() => Math.round(telemetry.fuel));

function initWebSocket(): void {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('[Vue Dashboard] Connected to server.');
  };

  ws.onmessage = (event: MessageEvent) => {
    try {
      const data: ServerToClientMessage = JSON.parse(event.data);
      handleServerMessage(data);
    } catch (e) {
      console.error('[Vue Dashboard] Message parse error:', e);
    }
  };

  ws.onclose = () => {
    isConnected.value = false;
    statusMessage.value = 'Disconnected from Server';
    setTimeout(initWebSocket, 3000);
  };

  ws.onerror = (err) => {
    console.error('[Vue Dashboard] WebSocket error:', err);
  };
}

function handleServerMessage(msg: ServerToClientMessage): void {
  if (msg.type === 'engine_status') {
    isConnected.value = msg.connected;
    statusMessage.value = msg.message;
  } else if (msg.type === 'telemetry') {
    Object.assign(telemetry, msg.data);
  } else if (msg.type === 'log') {
    appendLog(msg.timestamp || new Date().toLocaleTimeString(), msg.message);
  } else if (msg.type === 'screenshot') {
    if (debugStreamActive.value) {
      debugImageSrc.value = msg.image;
    }
  }
}

function appendLog(timestamp: string, message: string, isSystem = false): void {
  logs.value.push({
    id: logIdCounter++,
    timestamp,
    message,
    isSystem
  });
  nextTick(() => {
    if (logConsole.value) {
      logConsole.value.scrollTop = logConsole.value.scrollHeight;
    }
  });
}

function sendCommand(command: string, extraData: Record<string, any> = {}): void {
  if (ws && ws.readyState === WebSocket.OPEN) {
    const payload: CommandMessage = { command, ...extraData };
    ws.send(JSON.stringify(payload));
  } else {
    appendLog(new Date().toLocaleTimeString(), 'Error: Cannot send command, WebSocket disconnected.');
  }
}

function toggleAssist(assistName: string): void {
  const isCurrentlyActive = telemetry.assists[assistName] || false;
  const cmd = isCurrentlyActive ? `stop_${assistName}` : `start_${assistName}`;
  sendCommand(cmd);
}

function stopAllAssists(): void {
  sendCommand('stop_all_assists');
}

function loadWaypointFile(): void {
  if (waypointFilepath.value.trim()) {
    sendCommand('load_waypoint_file', { filepath: waypointFilepath.value.trim() });
  }
}

function toggleDebugStream(): void {
  debugStreamActive.value = !debugStreamActive.value;
  if (!debugStreamActive.value) {
    debugImageSrc.value = '';
  }
  sendCommand('toggle_debug_stream', { enabled: debugStreamActive.value });
}

function clearLogs(): void {
  logs.value = [];
}

onMounted(() => {
  initWebSocket();
});
</script>

<template>
  <div class="app-container">
    <!-- Header -->
    <header class="app-header">
      <div class="logo-group">
        <span class="logo-icon">🚀</span>
        <h1>ED AUTOPILOT <span class="badge">VUE + TS</span></h1>
      </div>
      <div class="status-indicator" id="connection-status">
        <span :class="['status-dot', isConnected ? 'connected' : 'disconnected']"></span>
        <span class="status-text">{{ statusMessage }}</span>
      </div>
    </header>

    <!-- Dashboard Content Grid -->
    <main class="dashboard-grid">
      <!-- Left Column: Telemetry & Controls -->
      <section class="left-panel">
        <!-- Telemetry Card -->
        <div class="card telemetry-card">
          <h2><span class="icon">📊</span> Telemetry & State</h2>
          <div class="telemetry-grid">
            <div class="telemetry-item">
              <span class="label">Status</span>
              <span class="value highlight">{{ telemetry.status }}</span>
            </div>
            <div class="telemetry-item">
              <span class="label">Current System</span>
              <span class="value">{{ telemetry.system }}</span>
            </div>
            <div class="telemetry-item">
              <span class="label">Ship Type</span>
              <span class="value">{{ telemetry.ship }}</span>
            </div>
            <div class="telemetry-item">
              <span class="label">Fuel Level</span>
              <div class="fuel-container">
                <div class="fuel-bar-bg">
                  <div class="fuel-bar-fill" :style="{ width: roundedFuel + '%' }"></div>
                </div>
                <span class="fuel-text">{{ roundedFuel }}%</span>
              </div>
            </div>
            <div class="telemetry-item full-width">
              <span class="label">Jump Info</span>
              <span class="value">{{ telemetry.jump_info }}</span>
            </div>
          </div>
        </div>

        <!-- Control Panel Card -->
        <div class="card control-card">
          <h2><span class="icon">🎮</span> Autopilot Assists Control Panel</h2>
          <div class="control-buttons-grid">
            <button
              :class="['btn', 'btn-primary', { active: telemetry.assists.waypoint }]"
              @click="toggleAssist('waypoint')"
            >
              <span class="btn-icon">📍</span>
              <span class="btn-text">{{ telemetry.assists.waypoint ? 'Stop Waypoint Assist' : 'Start Waypoint Assist' }}</span>
            </button>

            <button
              :class="['btn', 'btn-primary', { active: telemetry.assists.fsd }]"
              @click="toggleAssist('fsd')"
            >
              <span class="btn-icon">🌌</span>
              <span class="btn-text">{{ telemetry.assists.fsd ? 'Stop FSD Assist' : 'Start FSD Assist' }}</span>
            </button>

            <button
              :class="['btn', 'btn-primary', { active: telemetry.assists.sc }]"
              @click="toggleAssist('sc')"
            >
              <span class="btn-icon">💫</span>
              <span class="btn-text">{{ telemetry.assists.sc ? 'Stop SC Assist' : 'Start SC Assist' }}</span>
            </button>

            <button
              :class="['btn', 'btn-secondary', { active: telemetry.assists.robigo }]"
              @click="toggleAssist('robigo')"
            >
              <span class="btn-icon">🛸</span>
              <span class="btn-text">{{ telemetry.assists.robigo ? 'Stop Robigo Assist' : 'Start Robigo Assist' }}</span>
            </button>

            <button
              :class="['btn', 'btn-secondary', { active: telemetry.assists.dss }]"
              @click="toggleAssist('dss')"
            >
              <span class="btn-icon">📡</span>
              <span class="btn-text">{{ telemetry.assists.dss ? 'Stop DSS Assist' : 'Start DSS Assist' }}</span>
            </button>

            <button class="btn btn-danger full-width" @click="stopAllAssists">
              <span class="btn-icon">🛑</span>
              <span class="btn-text">STOP ALL ASSISTS</span>
            </button>
          </div>
        </div>

        <!-- Waypoint File Loader Card -->
        <div class="card waypoint-card">
          <h2><span class="icon">📁</span> Waypoint Route</h2>
          <div class="input-group">
            <input type="text" v-model="waypointFilepath" placeholder="e.g. waypoints/route.json">
            <button class="btn btn-accent" @click="loadWaypointFile">Load File</button>
          </div>
        </div>
      </section>

      <!-- Right Column: Live Debug Stream & Console Logs -->
      <section class="right-panel">
        <!-- Live Debug Screenshots Stream -->
        <div class="card screenshot-card">
          <div class="card-header">
            <h2><span class="icon">👁️</span> Live OpenCV Debug View</h2>
            <button
              :class="['btn', 'btn-sm', 'btn-outline', { active: debugStreamActive }]"
              @click="toggleDebugStream"
            >
              {{ debugStreamActive ? 'Disable Stream' : 'Enable Stream' }}
            </button>
          </div>
          <div class="stream-container">
            <img v-if="debugStreamActive && debugImageSrc" :src="debugImageSrc" alt="Debug Frame Stream" />
            <div v-else class="placeholder">
              <span>Live OpenCV debug frame streaming {{ debugStreamActive ? 'waiting for frames...' : 'inactive' }}</span>
            </div>
          </div>
        </div>

        <!-- Terminal Log Viewer -->
        <div class="card log-card">
          <div class="card-header">
            <h2><span class="icon">📜</span> Real-time Console Log Feed</h2>
            <button class="btn btn-sm btn-outline" @click="clearLogs">Clear</button>
          </div>
          <div class="log-console" ref="logConsole">
            <div
              v-for="entry in logs"
              :key="entry.id"
              :class="['log-entry', { system: entry.isSystem }]"
            >
              [{{ entry.timestamp }}] {{ entry.message }}
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>
