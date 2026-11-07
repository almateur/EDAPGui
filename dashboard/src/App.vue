<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount, computed, nextTick } from 'vue';
import WaypointRouteEditor from './WaypointRouteEditor.vue';
import CalibrationStatus from './CalibrationStatus.vue';
import { parseWaypointRoute, serializeWaypointRoute, MAX_WAYPOINT_BYTES, type WaypointRoute } from './waypointRoute';
import type { TelemetryData, ServerToClientMessage, CommandMessage, CalibrationStatusMessage } from './types';

// Reactive state
const isConnected = ref(false);
const calibrationStatus = ref<CalibrationStatusMessage | null>(null);
const assistError = ref('');
const statusMessage = ref('Connecting to Engine...');
const isBuildingPython = ref(false);
const isBackendRunning = ref(false);
const isBackendManaged = ref(false);
const hasProcessStatus = ref(false);
const backendPid = ref<number | null>(null);
const debugStreamActive = ref(false);
const debugImageSrc = ref('');
const waypointFilename = ref('');
const waypointFileInput = ref<HTMLInputElement | null>(null);
const isLoadingWaypoint = ref(false);
const waypointMessage = ref('');
const waypointError = ref(false);
const waypointRoute = ref<WaypointRoute | null>(null);
const originalRouteJSON = ref('');
const appliedRouteJSON = ref('');
const downloadedRouteJSON = ref('');
let pendingRouteJSON: string | null = null;
const routeValidation = computed(() => {
  if (!waypointRoute.value) return { json: '', error: '' };
  try { return { json: serializeWaypointRoute(waypointRoute.value), error: '' }; }
  catch (error) { return { json: '', error: error instanceof Error ? error.message : 'Invalid route.' }; }
});
const hasRouteEdits = computed(() => !!waypointRoute.value && (!!routeValidation.value.error || routeValidation.value.json !== originalRouteJSON.value));
const hasUnsavedRouteEdits = computed(() => hasRouteEdits.value && (!routeValidation.value.json || routeValidation.value.json !== downloadedRouteJSON.value));
const routeApplied = computed(() => !!routeValidation.value.json && routeValidation.value.json === appliedRouteJSON.value);
let pendingWaypointRequest: string | null = null;
let waypointLoadTimer: ReturnType<typeof setTimeout> | null = null;
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
const backendStatusLabel = computed(() => {
  if (!hasProcessStatus.value) return 'Checking...';
  if (!isBackendRunning.value) return 'Stopped';
  if (!isBackendManaged.value) return 'Running (started separately)';
  return backendPid.value ? `Running (PID: ${backendPid.value})` : 'Running';
});

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
    if (pendingWaypointRequest) finishWaypointLoad('Connection lost before the waypoint file was loaded.', true);
    isConnected.value = false;
    calibrationStatus.value = null;
    hasProcessStatus.value = false;
    isBackendRunning.value = false;
    isBackendManaged.value = false;
    backendPid.value = null;
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
    if (!msg.connected) calibrationStatus.value = null;
    else if (!calibrationStatus.value) sendCommand('check_calibration');
    if (!msg.connected && pendingWaypointRequest) finishWaypointLoad('The Python backend disconnected before loading the file.', true);
  } else if (msg.type === 'calibration_status') {
    calibrationStatus.value = msg;
    if (msg.state === 'ready') assistError.value = '';
  } else if (msg.type === 'command_error') {
    assistError.value = msg.message;
    appendLog(new Date().toLocaleTimeString(), msg.message, true);
  } else if (msg.type === 'process_status') {
    hasProcessStatus.value = true;
    isBuildingPython.value = msg.building;
    isBackendRunning.value = msg.running;
    isBackendManaged.value = msg.managed;
    backendPid.value = msg.pid || null;
    if (msg.message) {
      appendLog(new Date().toLocaleTimeString(), `[Engine Manager] ${msg.message}`, true);
    }
  } else if (msg.type === 'telemetry') {
    Object.assign(telemetry, msg.data);
  } else if (msg.type === 'log') {
    appendLog(msg.timestamp || new Date().toLocaleTimeString(), msg.message);
  } else if (msg.type === 'screenshot') {
    if (debugStreamActive.value) {
      debugImageSrc.value = msg.image;
    }
  } else if (msg.type === 'waypoint_load_result' && msg.request_id === pendingWaypointRequest) {
    if (msg.success && pendingRouteJSON) {
      appliedRouteJSON.value = pendingRouteJSON;
      originalRouteJSON.value = pendingRouteJSON;
    }
    finishWaypointLoad(`${waypointFilename.value}: ${msg.message}`, !msg.success);
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

function sendCommand(command: string, extraData: Record<string, any> = {}): boolean {
  if (ws && ws.readyState === WebSocket.OPEN) {
    const payload: CommandMessage = { command, ...extraData };
    ws.send(JSON.stringify(payload));
    return true;
  } else {
    appendLog(new Date().toLocaleTimeString(), 'Error: Cannot send command, WebSocket disconnected.');
    return false;
  }
}

function buildPythonEngine(): void {
  appendLog(new Date().toLocaleTimeString(), 'Initiating Python build & dependency setup...', true);
  sendCommand('build_python');
}

function startPythonBackend(): void {
  appendLog(new Date().toLocaleTimeString(), 'Starting Python Backend Server process...', true);
  sendCommand('start_python_backend');
}

function stopPythonBackend(): void {
  appendLog(new Date().toLocaleTimeString(), 'Stopping Python Backend Server process...', true);
  sendCommand('stop_python_backend');
}

function toggleAssist(assistName: string): void {
  assistError.value = '';
  const isCurrentlyActive = telemetry.assists[assistName] || false;
  const cmd = isCurrentlyActive ? `stop_${assistName}` : `start_${assistName}`;
  sendCommand(cmd);
}

function stopAllAssists(): void {
  sendCommand('stop_all_assists');
}

function assistStartDisabled(name: string): boolean {
  if (telemetry.assists[name]) return false; // A stop must always remain available.
  if (!isConnected.value) return true;
  return !calibrationStatus.value || calibrationStatus.value.blocked_assists.includes(name);
}

function loadWaypointFile(): void {
  waypointFileInput.value?.click();
}

function finishWaypointLoad(message: string, error = false): void {
  if (waypointLoadTimer) clearTimeout(waypointLoadTimer);
  waypointLoadTimer = null;
  pendingWaypointRequest = null;
  pendingRouteJSON = null;
  isLoadingWaypoint.value = false;
  waypointMessage.value = message;
  waypointError.value = error;
}

async function onWaypointFileSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = ''; // Selecting the same file again must also trigger change.
  if (!file || isLoadingWaypoint.value) return;
  if (hasUnsavedRouteEdits.value && !window.confirm('Discard the edits to this route and open another file? Download JSON to keep your changes.')) return;
  isLoadingWaypoint.value = true;
  try {
    if (!file.name.toLowerCase().endsWith('.json')) throw new Error('Choose a JSON waypoint file.');
    if (file.size > MAX_WAYPOINT_BYTES) throw new Error('Waypoint files must be at most 1 MiB.');
    const route = parseWaypointRoute(await file.text());
    waypointRoute.value = route;
    waypointFilename.value = file.name;
    originalRouteJSON.value = serializeWaypointRoute(route);
    appliedRouteJSON.value = '';
    downloadedRouteJSON.value = '';
    isLoadingWaypoint.value = false;
    if (!isConnected.value) {
      finishWaypointLoad('Route opened for editing. Connect the Python backend to apply it, or download your JSON.');
    } else if (telemetry.assists.waypoint) {
      finishWaypointLoad('Route opened for editing. Stop Waypoint Assist before applying it.');
    } else {
      await applyWaypointRoute();
    }
  } catch (error) {
    finishWaypointLoad(error instanceof Error ? error.message : 'Unable to open the waypoint file.', true);
  }
}

async function applyWaypointRoute(): Promise<void> {
  if (!waypointRoute.value || isLoadingWaypoint.value) return;
  isLoadingWaypoint.value = true;
  waypointMessage.value = `Applying ${waypointFilename.value}...`;
  waypointError.value = false;
  try {
    const json = serializeWaypointRoute(waypointRoute.value);
    if (!waypointRoute.value.stops.length) throw new Error('Add a stop before applying this route.');
    if (!isConnected.value) throw new Error('Connect the Python backend before applying a waypoint route.');
    if (telemetry.assists.waypoint) throw new Error('Stop Waypoint Assist before applying a route.');
    const response = await fetch('/api/waypoints/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: json
    });
    if (!response.ok) {
      let message = 'Unable to import the waypoint file.';
      try { message = (await response.json()).error || message; } catch { /* Keep the useful fallback. */ }
      throw new Error(message);
    }
    const { filepath } = await response.json() as { filepath: string };
    if (!isConnected.value) throw new Error('The Python backend disconnected before loading the file.');
    pendingRouteJSON = json;
    pendingWaypointRequest = crypto.randomUUID();
    waypointLoadTimer = setTimeout(() => finishWaypointLoad('The backend did not confirm loading the file. Check the Python terminal for errors before retrying.', true), 15000);
    if (!sendCommand('load_waypoint_file', { filepath, request_id: pendingWaypointRequest })) {
      throw new Error('The dashboard connection is unavailable.');
    }
  } catch (error) {
    finishWaypointLoad(error instanceof Error ? error.message : 'Unable to apply the waypoint route.', true);
  }
}

function downloadWaypointRoute(): void {
  if (!routeValidation.value.json) return;
  const url = URL.createObjectURL(new Blob([routeValidation.value.json], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = waypointFilename.value.replace(/\.json$/i, '') + '-edited.json';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  downloadedRouteJSON.value = routeValidation.value.json;
}

function undoRouteEdits(): void {
  if (originalRouteJSON.value) waypointRoute.value = parseWaypointRoute(originalRouteJSON.value);
}

function protectRouteEdits(event: BeforeUnloadEvent): void {
  if (hasUnsavedRouteEdits.value) {
    event.preventDefault();
    event.returnValue = '';
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
  window.addEventListener('beforeunload', protectRouteEdits);
});
onBeforeUnmount(() => window.removeEventListener('beforeunload', protectRouteEdits));
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
      <CalibrationStatus :status="calibrationStatus" :connected="isConnected" @recheck="sendCommand('check_calibration')" />
      <!-- Left Column: Telemetry & Controls -->
      <section class="left-panel">
        <!-- Python Engine & Process Management Card -->
        <div class="card engine-card">
          <h2><span class="icon">⚙️</span> Python Engine Manager</h2>
          <div class="engine-status-row">
            <span class="label">Backend Process:</span>
            <span :class="['badge-status', hasProcessStatus ? (isBackendRunning ? 'status-running' : 'status-stopped') : 'status-building']">
              {{ backendStatusLabel }}
            </span>
            <span v-if="isBuildingPython" class="badge-status status-building">
              🔨 Building Environment...
            </span>
          </div>
          <div class="engine-buttons-grid">
            <button
              class="btn btn-secondary"
              :disabled="isBuildingPython"
              @click="buildPythonEngine"
            >
              <span class="btn-icon">📦</span>
              <span class="btn-text">{{ isBuildingPython ? 'Building...' : 'Build Python Env' }}</span>
            </button>

            <button
              v-if="hasProcessStatus && !isBackendRunning"
              class="btn btn-accent"
              :disabled="isBuildingPython"
              @click="startPythonBackend"
            >
              <span class="btn-icon">▶️</span>
              <span class="btn-text">Start Python Backend</span>
            </button>

            <button
              v-if="hasProcessStatus && isBackendManaged"
              class="btn btn-danger"
              @click="stopPythonBackend"
            >
              <span class="btn-icon">⏹️</span>
              <span class="btn-text">Stop Python Backend</span>
            </button>
          </div>
          <p v-if="hasProcessStatus && isBackendRunning && !isBackendManaged">
            This backend was started outside the dashboard. Stop it in the terminal or app where you launched it.
          </p>
        </div>

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
          <p v-if="assistError" class="assist-error" role="alert">{{ assistError }}</p>
          <div class="control-buttons-grid">
            <button
              :class="['btn', 'btn-primary', { active: telemetry.assists.waypoint }]"
              @click="toggleAssist('waypoint')"
              :disabled="assistStartDisabled('waypoint')"
            >
              <span class="btn-icon">📍</span>
              <span class="btn-text">{{ telemetry.assists.waypoint ? 'Stop Waypoint Assist' : 'Start Waypoint Assist' }}</span>
            </button>

            <button
              :class="['btn', 'btn-primary', { active: telemetry.assists.fsd }]"
              @click="toggleAssist('fsd')"
              :disabled="assistStartDisabled('fsd')"
            >
              <span class="btn-icon">🌌</span>
              <span class="btn-text">{{ telemetry.assists.fsd ? 'Stop FSD Assist' : 'Start FSD Assist' }}</span>
            </button>

            <button
              :class="['btn', 'btn-primary', { active: telemetry.assists.sc }]"
              @click="toggleAssist('sc')"
              :disabled="assistStartDisabled('sc')"
            >
              <span class="btn-icon">💫</span>
              <span class="btn-text">{{ telemetry.assists.sc ? 'Stop SC Assist' : 'Start SC Assist' }}</span>
            </button>

            <button
              :class="['btn', 'btn-secondary', { active: telemetry.assists.robigo }]"
              @click="toggleAssist('robigo')"
              :disabled="assistStartDisabled('robigo')"
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
      <section class="card waypoint-card">
        <div class="card-header">
          <h2><span class="icon">📁</span> Waypoint Route</h2>
          <span v-if="waypointRoute" class="route-state" :class="{ edited: hasRouteEdits, applied: routeApplied }">{{ hasRouteEdits ? 'Edited draft' : routeApplied ? 'Applied to backend' : 'Local preview' }}</span>
        </div>
        <div class="input-group">
          <input type="text" :value="waypointFilename" readonly aria-label="Selected waypoint file" placeholder="Choose a waypoint JSON file">
          <input ref="waypointFileInput" type="file" accept=".json,application/json" hidden @change="onWaypointFileSelected">
          <button class="btn btn-accent" :disabled="isLoadingWaypoint" @click="loadWaypointFile">{{ isLoadingWaypoint ? 'Loading...' : 'Load File' }}</button>
        </div>
        <p v-if="waypointMessage" :role="waypointError ? 'alert' : 'status'">{{ waypointMessage }}</p>
        <template v-if="waypointRoute">
          <WaypointRouteEditor v-model="waypointRoute" :busy="isLoadingWaypoint" :current-system="telemetry.system" />
          <p v-if="routeValidation.error" class="route-validation" role="alert">{{ routeValidation.error }}</p>
          <div class="route-save-bar">
            <p>{{ telemetry.assists.waypoint ? 'Stop Waypoint Assist to apply a route.' : 'Apply saves a working copy for the backend. Download JSON keeps a file on your computer.' }}</p>
            <div class="route-save-actions">
              <button class="btn btn-sm btn-outline" :disabled="isLoadingWaypoint || !hasRouteEdits" @click="undoRouteEdits">Undo edits</button>
              <button class="btn btn-secondary" :disabled="isLoadingWaypoint || !!routeValidation.error" @click="downloadWaypointRoute">Download JSON</button>
              <button class="btn btn-accent" :disabled="isLoadingWaypoint || !!routeValidation.error || !waypointRoute.stops.length || !isConnected || telemetry.assists.waypoint" @click="applyWaypointRoute">{{ isLoadingWaypoint ? 'Applying...' : 'Apply changes' }}</button>
            </div>
          </div>
        </template>
        <p v-else class="route-empty">Load a waypoint file to see its travel order and edit destinations, bookmarks, and trading. You can plan routes while the backend is offline.</p>
      </section>
    </main>
  </div>
</template>

<style scoped>
.control-card button:disabled { opacity: .45; cursor: not-allowed; }
.assist-error { color: var(--accent-red); margin-bottom: 12px; overflow-wrap: anywhere; }
.waypoint-card { grid-column: 1 / -1; min-width: 0; }
.route-state { color: var(--text-muted); font-size: .8rem; }
.waypoint-card :deep(button:disabled) { opacity: .45; cursor: not-allowed; }
.route-state.applied { color: var(--accent-green); }
.route-state.edited { color: var(--accent-orange); }
.route-validation { color: var(--accent-red); margin-top: 16px; font-size: .9rem; }
.route-save-bar { display: flex; align-items: center; justify-content: space-between; gap: 20px; flex-wrap: wrap; margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--border-color); }
.route-save-bar p, .route-empty { color: var(--text-muted); font-size: .85rem; }
.route-save-bar p { flex: 1 1 260px; }
.route-save-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.route-empty { margin-top: 16px; }
</style>
