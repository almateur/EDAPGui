let ws = null;
let activeAssists = {
  fsd: false,
  sc: false,
  waypoint: false,
  robigo: false,
  dss: false
};
let debugStreamActive = false;

function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log('[Dashboard Frontend] Connected to server.');
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleServerMessage(data);
    } catch (e) {
      console.error('[Dashboard Frontend] Message parse error:', e);
    }
  };

  ws.onclose = () => {
    updateConnectionStatus(false, 'Disconnected from Dashboard Server');
    setTimeout(initWebSocket, 3000);
  };

  ws.onerror = (err) => {
    console.error('[Dashboard Frontend] WebSocket error:', err);
  };
}

function updateConnectionStatus(connected, message) {
  const statusElem = document.getElementById('connection-status');
  const dot = statusElem.querySelector('.status-dot');
  const text = statusElem.querySelector('.status-text');

  if (connected) {
    dot.className = 'status-dot connected';
    text.textContent = message || 'Connected to Engine';
  } else {
    dot.className = 'status-dot disconnected';
    text.textContent = message || 'Disconnected';
  }
}

function handleServerMessage(msg) {
  if (msg.type === 'engine_status') {
    updateConnectionStatus(msg.connected, msg.message);
  } else if (msg.type === 'telemetry') {
    updateTelemetry(msg.data);
  } else if (msg.type === 'log') {
    appendLog(msg.timestamp || getTimestamp(), msg.message);
  } else if (msg.type === 'screenshot') {
    updateDebugScreenshot(msg.image);
  }
}

function updateTelemetry(data) {
  if (!data) return;

  if (data.status) {
    document.getElementById('tel-status').textContent = data.status;
  }
  if (data.system) {
    document.getElementById('tel-system').textContent = data.system;
  }
  if (data.ship) {
    document.getElementById('tel-ship').textContent = data.ship;
  }
  if (data.jump_info) {
    document.getElementById('tel-jumps').textContent = data.jump_info;
  }
  if (data.fuel !== undefined) {
    const fuelVal = Math.round(data.fuel);
    document.getElementById('tel-fuel').textContent = `${fuelVal}%`;
    document.getElementById('fuel-bar').style.width = `${fuelVal}%`;
  }

  if (data.assists) {
    activeAssists = { ...data.assists };
    updateButtonStates();
  }
}

function updateButtonStates() {
  setButtonState('btn-waypoint', activeAssists.waypoint, 'Start Waypoint Assist', 'Stop Waypoint Assist');
  setButtonState('btn-fsd', activeAssists.fsd, 'Start FSD Assist', 'Stop FSD Assist');
  setButtonState('btn-sc', activeAssists.sc, 'Start SC Assist', 'Stop SC Assist');
  setButtonState('btn-robigo', activeAssists.robigo, 'Start Robigo Assist', 'Stop Robigo Assist');
  setButtonState('btn-dss', activeAssists.dss, 'Start DSS Assist', 'Stop DSS Assist');
}

function setButtonState(btnId, isActive, defaultText, activeText) {
  const btn = document.getElementById(btnId);
  if (!btn) return;

  const btnText = btn.querySelector('.btn-text');
  if (isActive) {
    btn.classList.add('active');
    if (btnText) btnText.textContent = activeText;
  } else {
    btn.classList.remove('active');
    if (btnText) btnText.textContent = defaultText;
  }
}

function toggleAssist(assistName) {
  const isCurrentlyActive = activeAssists[assistName] || false;
  const cmd = isCurrentlyActive ? `stop_${assistName}` : `start_${assistName}`;

  sendSocketCommand(cmd);
}

function stopAllAssists() {
  sendSocketCommand('stop_all_assists');
}

function loadWaypointFile() {
  const filepath = document.getElementById('waypoint-filepath').value.trim();
  if (filepath) {
    sendSocketCommand('load_waypoint_file', { filepath });
  }
}

function toggleDebugStream() {
  debugStreamActive = !debugStreamActive;
  const btn = document.getElementById('btn-toggle-stream');

  if (debugStreamActive) {
    btn.textContent = 'Disable Stream';
    btn.classList.add('active');
  } else {
    btn.textContent = 'Enable Stream';
    btn.classList.remove('active');
    document.getElementById('debug-stream-img').classList.add('hidden');
    document.getElementById('stream-placeholder').style.display = 'block';
  }

  sendSocketCommand('toggle_debug_stream', { enabled: debugStreamActive });
}

function updateDebugScreenshot(imageB64) {
  if (!debugStreamActive) return;

  const imgElem = document.getElementById('debug-stream-img');
  const placeholder = document.getElementById('stream-placeholder');

  imgElem.src = imageB64;
  imgElem.classList.remove('hidden');
  placeholder.style.display = 'none';
}

function sendSocketCommand(command, extraData = {}) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    const payload = { command, ...extraData };
    ws.send(JSON.stringify(payload));
  } else {
    appendLog(getTimestamp(), 'Error: Cannot send command, WebSocket disconnected.');
  }
}

function appendLog(timestamp, message) {
  const consoleElem = document.getElementById('log-console');
  const entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.textContent = `[${timestamp}] ${message}`;

  consoleElem.appendChild(entry);
  consoleElem.scrollTop = consoleElem.scrollHeight;
}

function clearLogs() {
  document.getElementById('log-console').innerHTML = '';
}

function getTimestamp() {
  return new Date().toLocaleTimeString();
}

window.addEventListener('DOMContentLoaded', () => {
  initWebSocket();
});
