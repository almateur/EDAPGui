<script setup lang="ts">
import type { CalibrationStatusMessage } from './types';
defineProps<{ status: CalibrationStatusMessage | null; connected: boolean }>();
defineEmits<{ recheck: [] }>();
</script>

<template>
  <aside v-if="connected" class="card calibration-card" :class="{ ready: status?.state === 'ready', simulated: status?.mock }" :role="status && status.state !== 'ready' && !status.mock ? 'alert' : 'status'" aria-labelledby="calibration-heading">
    <div class="calibration-heading">
      <h2 id="calibration-heading">{{ !status ? 'Checking screen calibration…' : status.mock ? 'Mock mode — controls are simulated' : status.state === 'ready' ? 'Screen calibration configured' : status.state === 'restart_required' ? 'Restart backend to load calibration' : 'Screen calibration required' }}</h2>
      <button class="btn btn-sm btn-outline" @click="$emit('recheck')">Recheck calibration</button>
    </div>
    <p>{{ status?.message || 'Waiting for calibration status. If this persists, update and restart the Python backend.' }}</p>
    <template v-if="status && status.state !== 'ready'">
      <p v-if="status.mock">Calibration is required for live automation. Mock controls remain available for testing.</p>
      <p v-else-if="status.blocked_assists.length">Affected assists cannot start until calibration is complete and loaded.</p>
      <p v-if="status.state === 'invalid'">Back up and rename the invalid calibration file before opening the desktop app so it can create a fresh file.</p>
      <p v-if="status.restart_required && status.state !== 'restart_required'">The file has changed. After fixing the remaining regions, restart the Python backend to load them.</p>
      <details v-if="status.issues.length" class="calibration-issues">
        <summary>Calibration problems ({{ status.issues.length }})</summary>
        <ul><li v-for="issue in status.issues" :key="issue">{{ issue }}</li></ul>
      </details>
      <ol class="calibration-steps">
        <li>Stop the Python backend. With Elite Dangerous visible in Borderless mode, open <code>EDAPGui.py</code> using your Python environment.</li>
        <li>In the desktop app’s <strong>Calibration</strong> tab, calibrate <code>Screen_Regions.full_panel</code> and <code>EDCodex.full_panel</code>, then click <strong>Save All Calibrations</strong>. This calculates the Galaxy Map and System Map bounds.</li>
        <li>Close the desktop app and restart <code>backend_server.py</code> to load the saved calibration.</li>
      </ol>
      <p><a href="https://github.com/almateur/EDAPGui/blob/main/docs/Calibration.md" target="_blank" rel="noopener noreferrer">Calibration guide</a> · <code>{{ status.file }}</code></p>
    </template>
  </aside>
</template>

<style scoped>
.calibration-card { grid-column: 1 / -1; border-color: var(--accent-orange); min-width: 0; }
.calibration-card.ready { border-color: var(--accent-green); }
.calibration-card.simulated { border-color: var(--accent-cyan); }
.calibration-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.calibration-heading h2 { margin: 0; font-size: 1rem; }
p, li, summary { font-size: .9rem; }
p { margin-top: 10px; }
.calibration-steps, .calibration-issues ul { padding-left: 24px; margin: 12px 0; }
li { margin: 6px 0; overflow-wrap: anywhere; }
.calibration-issues { margin-top: 12px; }
summary { cursor: pointer; }
code { overflow-wrap: anywhere; color: var(--accent-cyan); font-size: .85rem; }
a { color: var(--accent-cyan); }
</style>
