<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { ShipInfoMessage, ShipModule, FlightInfo } from './types';
const props = defineProps<{ info: ShipInfoMessage | null; flight?: FlightInfo; connected: boolean; calibrationReady: boolean; pending: boolean; message: string; error: boolean }>();
const emit = defineEmits<{ refresh: []; tune: [enabled: boolean]; save: [] }>();
const search = ref('');
const engineeredOnly = ref(false);
const expanded = ref(new Set<string>());
const curveMode = ref('SCSpeed50');
const modules = computed(() => Array.isArray(props.info?.loadout?.Modules)
  ? props.info!.loadout!.Modules!.filter(module => module && typeof module.Slot === 'string' && typeof module.Item === 'string') : []);
const engineered = computed(() => modules.value.filter(module => !!module.Engineering).length);
const filtered = computed(() => modules.value.filter(module => {
  const query = search.value.toLowerCase().trim();
  return (!engineeredOnly.value || !!module.Engineering) && (!query ||
    [module.Slot, module.Item, module.Item_Localised, module.Engineering?.BlueprintName,
      module.Engineering?.Engineer, module.Engineering?.ExperimentalEffect].some(value => typeof value === 'string' && value.toLowerCase().includes(query)));
}));
watch(() => props.info?.build_signature, () => { expanded.value = new Set(); search.value = ''; });
const profile = computed(() => props.info?.profile);
const waiting = computed(() => props.info?.stale || !props.info?.identity_known || profile.value?.pending);
const source = computed(() => ({ ship_defaults: 'Ship defaults · 50% supercruise', generic_defaults: 'Generic fallback estimates', legacy_unverified: 'Legacy settings · unverified for this build' })[profile.value?.seed_source ?? ''] ?? 'Unavailable');
const stats = computed(() => Object.entries(props.info?.loadout ?? {}).filter(([key]) =>
  !['Modules', 'event', 'timestamp', 'Ship', 'ShipID', 'ShipName', 'ShipIdent'].includes(key)));
const modes = { Speed0: 'Normal space · 0%', Speed50: 'Normal space · 50%', Speed100: 'Normal space · 100%',
  SCSpeed0: 'Supercruise · 0%', SCSpeed50: 'Supercruise · 50%', SCSpeed100: 'Supercruise · 100%' };
const axes = ['RollRate', 'PitchRate', 'YawRate'] as const;
const equipment = { has_fuel_scoop: 'Fuel scoop', has_adv_dock_comp: 'Advanced docking computer', has_std_dock_comp: 'Standard docking computer', has_sco_fsd: 'SCO FSD', has_supercruise_assist: 'Supercruise assist' };
const label = (value: string) => value.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/_/g, ' ');
function format(value: unknown): string {
  if (value === undefined || value === null) return 'Unknown';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : 'Unknown';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
function toggle(slot: string): void {
  const next = new Set(expanded.value);
  if (next.has(slot)) next.delete(slot); else next.add(slot);
  expanded.value = next;
}
function tune(event: Event): void {
  const input = event.target as HTMLInputElement;
  const enabled = input.checked;
  input.checked = !!(profile.value?.auto_tune_requested ?? profile.value?.auto_tune);
  emit('tune', enabled);
}
function download(): void {
  if (!props.info) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify({ ...props.info, live_flight: props.flight }, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `ship-${props.info.ship_id ?? 'unknown'}-${props.info.build_signature?.slice(0, 8) ?? 'loadout'}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function modifierValue(module: ShipModule): string {
  return module.Engineering ? `${module.Engineering.BlueprintName ?? 'Engineered'}${module.Engineering.Level != null ? ` · G${module.Engineering.Level}` : ''}` : 'No engineering reported';
}
function modifiers(module: ShipModule) {
  const values = module.Engineering?.Modifiers;
  return Array.isArray(values) ? values.filter(value => value && typeof value === 'object' && typeof value.Label === 'string') : [];
}
</script>

<template>
  <section v-if="connected" class="card ship-info-card" aria-labelledby="ship-info-heading">
    <div class="ship-heading">
      <div><h2 id="ship-info-heading">Ship &amp; engineering</h2><p v-if="info?.available" class="ship-name">{{ info.ship_name || info.ship_type }} <span v-if="info.ship_ident" class="muted">· {{ info.ship_ident }}</span></p></div>
      <div class="ship-actions"><button class="btn btn-sm btn-outline" :disabled="pending" @click="emit('refresh')">Refresh ship data</button><button class="btn btn-sm btn-outline" :disabled="!info?.available" @click="download">Export ship JSON</button></div>
    </div>
    <p v-if="!info?.available" class="muted">{{ info?.message || 'Waiting for ship data from the Python backend. Update and restart the backend if this persists.' }}</p>
    <template v-else>
      <div v-if="waiting" class="ship-warning" role="status">{{ info.reason || (profile?.pending ? 'A ship or build change was detected. Its profile will load when the controller is idle.' : 'Waiting for commander and ship identity before saving build-specific tuning.') }}</div>
      <div class="ship-summary">
        <div><span>Ship type</span><strong>{{ info.ship_type_name || info.ship_type }}<small v-if="info.ship_size"> · {{ info.ship_size }}</small></strong></div>
        <div><span>Ship ID</span><strong>{{ info.ship_id ?? 'Unknown' }}</strong></div>
        <div><span>Fitted modules</span><strong>{{ modules.length }} <small>· {{ engineered }} engineered</small></strong></div>
        <div><span>Build</span><strong :title="info.build_signature ?? ''">{{ info.build_signature?.slice(0, 12) ?? 'Awaiting loadout' }}</strong></div>
        <div><span>Flight mode</span><strong>{{ flight?.mode === 'supercruise' ? 'Supercruise' : flight?.mode === 'normal' ? 'Normal space' : 'Unknown' }}</strong></div>
        <div><span>Engine pips</span><strong>{{ flight?.pips?.engine ?? 'Unknown' }} <small v-if="flight?.pips">· SYS {{ flight.pips.system }} / WEP {{ flight.pips.weapons }}</small></strong></div>
        <div><span>Live cargo</span><strong>{{ flight?.cargo == null ? 'Unknown' : format(flight.cargo) + ' t' }}</strong></div>
        <div><span>Fuel main / reserve</span><strong>{{ format(flight?.fuel?.FuelMain) }} / {{ format(flight?.fuel?.FuelReservoir) }} t</strong></div>
      </div>
      <p class="muted source-time">Loadout reported by the game: {{ info.loadout?.timestamp || 'Unknown time' }}<span v-if="flight?.stale"> · Live status is unavailable; displaying the last reading.</span></p>
      <div class="equipment-list"><span v-for="(name, key) in equipment" :key="key" :class="{ fitted: info.equipment?.[key] === true }">{{ name }}: {{ info.equipment?.[key] == null ? 'Unknown' : info.equipment[key] ? 'Fitted' : 'Not fitted' }}</span></div>

      <div v-if="profile" class="tuning-panel">
        <div class="ship-heading"><h3>Rotation tuning</h3><span class="tuning-source">{{ profile.measured_points ? `${profile.measured_points} measured curve point${profile.measured_points === 1 ? '' : 's'} · partial tuning` : 'Starting estimates · measurement needed' }}</span></div>
        <p class="muted">{{ source }}. Engineering details do not directly provide rotation rates. Normal-space thruster bonuses are not applied to supercruise.</p>
        <div class="rate-grid"><div v-for="axis in axes" :key="axis"><span>{{ axis.replace('Rate', '') }} starting rate</span><strong>{{ format(profile.rates[axis]) }} <small>°/s</small></strong></div></div>
        <div class="tuning-actions">
          <label><input type="checkbox" aria-label="Learn rotation rates during assists" :checked="profile.auto_tune_requested ?? profile.auto_tune" :disabled="pending || (!(profile.auto_tune_requested ?? profile.auto_tune) && (!profile.can_tune || !calibrationReady || info.mock))" @change="tune"> Learn rotation rates during assists</label>
          <button class="btn btn-sm btn-outline" :disabled="pending || !profile.can_tune || info.mock" @click="emit('save')">Save tuning now</button>
          <span class="muted">{{ pending ? 'Updating…' : profile.dirty ? 'Changes awaiting autosave' : profile.saved_at ? 'Saved for this ship and build' : 'Not saved' }}</span>
        </div>
        <p class="muted">Learning uses the existing assist corrections and autosaves to this build. Screen calibration is required. Normal-space response also depends on mass and engine pips.</p>
        <p v-if="profile.auto_tune_requested && !profile.auto_tune" class="muted">Learning is paused until a complete, current ship profile is available.</p>
        <p v-if="message" :class="{ 'ship-error': error }" :role="error ? 'alert' : 'status'">{{ message }}</p>
        <p v-if="profile.save_error" class="ship-error" role="alert">Tuning could not be saved: {{ profile.save_error }}</p>
        <details class="ship-details"><summary>Tuning curves and measured points</summary>
          <label class="mode-picker">Flight mode and throttle <select v-model="curveMode"><option v-for="(name, key) in modes" :key="key" :value="key">{{ name }}</option></select></label>
          <div class="curve-grid"><table v-for="axis in axes" :key="axis"><caption>{{ axis.replace('Rate', '') }}</caption><thead><tr><th>Angle °</th><th>Rate °/s</th><th>Source</th></tr></thead><tbody><tr v-for="(rate, angle) in profile.curves[curveMode]?.[axis]" :key="angle"><td>{{ angle }}</td><td>{{ format(rate) }}</td><td>{{ profile.measured[curveMode]?.[axis]?.[angle] ? 'Measured' : 'Estimate' }}</td></tr></tbody></table></div>
        </details>
      </div>

      <details class="ship-details"><summary>Reported ship statistics ({{ stats.length }})</summary><dl class="stats-grid"><template v-for="[key, value] in stats" :key="key"><dt>{{ label(key) }}</dt><dd>{{ format(value) }}</dd></template></dl></details>
      <details class="ship-details module-details"><summary>Modules and engineering ({{ modules.length }})</summary>
        <div class="module-filter"><input v-model="search" type="search" aria-label="Search ship modules" placeholder="Search slot, module, blueprint or engineer…"><label><input v-model="engineeredOnly" type="checkbox"> Engineered only</label><span class="muted">{{ filtered.length }} shown</span></div>
        <div class="module-table-wrap"><table class="module-table"><thead><tr><th>Slot</th><th>Module</th><th>Engineering</th><th>Health</th><th>Power</th><th></th></tr></thead><tbody>
          <template v-for="module in filtered" :key="module.Slot">
            <tr><td>{{ module.Slot }}</td><td>{{ module.Item_Localised || module.Item }}</td><td>{{ modifierValue(module) }}</td><td>{{ typeof module.Health === 'number' ? format(module.Health * 100) + '%' : 'Unknown' }}</td><td>{{ module.On == null ? 'Unknown' : module.On ? 'On' : 'Off' }}<small v-if="module.Priority != null"> · P{{ module.Priority }}</small></td><td><button class="btn btn-sm btn-outline" :aria-label="`Inspect ${module.Slot}`" :aria-expanded="expanded.has(module.Slot)" @click="toggle(module.Slot)">{{ expanded.has(module.Slot) ? 'Close' : 'Inspect' }}</button></td></tr>
            <tr v-if="expanded.has(module.Slot)"><td colspan="6" class="module-expanded">
              <p v-if="module.Engineering">Engineer: {{ module.Engineering.Engineer || 'Unknown' }} · Quality: {{ format(module.Engineering.Quality) }} · Experimental: {{ module.Engineering.ExperimentalEffect_Localised || module.Engineering.ExperimentalEffect || 'None reported' }}</p>
              <table v-if="modifiers(module).length" class="modifier-table"><thead><tr><th>Modifier</th><th>Original</th><th>Engineered</th><th>Preferred value</th></tr></thead><tbody><tr v-for="(modifier, index) in modifiers(module)" :key="index"><td>{{ label(modifier.Label) }}</td><td>{{ format(modifier.OriginalValue) }}</td><td>{{ modifier.ValueStr ?? format(modifier.Value) }}</td><td>{{ modifier.LessIsGood == null ? 'Not reported' : modifier.LessIsGood ? 'Lower' : 'Higher' }}</td></tr></tbody></table>
              <details><summary>All module fields</summary><pre>{{ JSON.stringify(module, null, 2) }}</pre></details>
            </td></tr>
          </template>
          <tr v-if="!filtered.length"><td colspan="6">No matching modules.</td></tr>
        </tbody></table></div>
      </details>
      <details class="ship-details"><summary>Raw journal and status data</summary><pre>{{ JSON.stringify({ loadout: info.loadout, events: info.events, status: info.raw_status, live_flight: flight }, null, 2) }}</pre></details>
    </template>
  </section>
</template>

<style scoped>
.ship-info-card { grid-column: 1 / -1; min-width: 0; }
.ship-heading, .ship-actions, .tuning-actions, .module-filter { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.ship-heading { justify-content: space-between; }
.ship-heading h2 { margin: 0; }
h3 { font-size: 1rem; }
p { margin-top: 10px; font-size: .85rem; }
.ship-name { color: var(--accent-cyan); font-size: 1rem; }
.muted, small { color: var(--text-muted); font-size: .8rem; }
.ship-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin: 20px 0 10px; }
.ship-summary > div, .rate-grid > div { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.ship-summary span, .rate-grid span { color: var(--text-muted); font-size: .8rem; }
strong { font-size: .95rem; overflow-wrap: anywhere; }
.ship-warning { margin-top: 14px; padding: 12px; border: 1px solid var(--accent-orange); border-radius: 6px; color: var(--accent-orange); font-size: .85rem; }
.tuning-panel { margin-top: 20px; padding: 16px; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 8px; }
.equipment-list { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.equipment-list span { color: var(--text-muted); border: 1px solid var(--border-color); padding: 3px 7px; border-radius: 4px; font-size: .75rem; }
.equipment-list .fitted { color: var(--accent-green); }
.tuning-source { color: var(--accent-orange); font-size: .8rem; }
.rate-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 16px 0; }
.rate-grid strong { color: var(--accent-cyan); font-size: 1.25rem; }
.tuning-actions label, .module-filter label { display: flex; align-items: center; gap: 8px; font-size: .85rem; }
input[type=checkbox] { accent-color: var(--accent-cyan); }
.ship-details { margin-top: 16px; border-top: 1px solid var(--border-color); padding-top: 14px; min-width: 0; }
summary { cursor: pointer; font-size: .9rem; }
details[open] > summary { margin-bottom: 12px; }
.module-filter { margin-bottom: 14px; }
.module-filter > input { flex: 1 1 220px; }
input[type=search], select { padding: 9px; background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border-color); border-radius: 5px; min-width: 0; font: inherit; font-size: .85rem; }
.module-table-wrap { overflow: auto; max-height: 600px; }
table { width: 100%; border-collapse: collapse; font-size: .8rem; }
.module-table { min-width: 730px; }
th, td { padding: 10px; text-align: left; border-bottom: 1px solid var(--border-color); overflow-wrap: anywhere; }
th { color: var(--text-muted); font-weight: 500; }
.module-expanded { background: var(--bg-primary); }
.module-expanded > details { margin-top: 14px; }
.modifier-table { margin-top: 12px; }
.curve-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }
caption { text-align: left; color: var(--accent-cyan); }
.mode-picker { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: .85rem; }
.stats-grid { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(0, 3fr); gap: 8px 16px; font-size: .85rem; }
dt { color: var(--text-muted); }
dd { overflow-wrap: anywhere; }
pre { max-height: 400px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px; margin-top: 12px; background: var(--bg-primary); font-size: .75rem; }
.ship-error { color: var(--accent-red); }
button:disabled { opacity: .45; cursor: not-allowed; }
@media (max-width: 700px) { .ship-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } .curve-grid { grid-template-columns: 1fr; } .stats-grid { grid-template-columns: 1fr; gap: 3px; } dd { margin-bottom: 8px; } }
</style>
