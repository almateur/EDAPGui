<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import CommodityEditor from './CommodityEditor.vue';
import { addWaypoint, moveWaypoint, type WaypointRoute } from './waypointRoute';

const route = defineModel<WaypointRoute>({ required: true });
defineProps<{ busy: boolean; currentSystem: string }>();
const selectedId = ref<number | null>(null);
watch(() => route.value.id, () => { selectedId.value = route.value.stops[0]?.id ?? null; }, { immediate: true });
const selected = computed(() => route.value.stops.find(stop => stop.id === selectedId.value));
const selectedIndex = computed(() => route.value.stops.findIndex(stop => stop.id === selectedId.value));
const stats = computed(() => ({
  skipped: route.value.stops.filter(stop => stop.fields.Skip).length,
  completed: route.value.stops.filter(stop => stop.fields.Completed && !stop.fields.Skip).length,
  pending: route.value.stops.filter(stop => !stop.fields.Skip && !stop.fields.Completed && !isRepeat(stop.fields.SystemName)).length
}));
const isRepeat = (name: string) => name.trim().toUpperCase() === 'REPEAT';
const hasBookmark = (fields: WaypointRoute['stops'][number]['fields']) => fields.GalaxyBookmarkNumber > 0 || fields.SystemBookmarkNumber > 0;
const hasRepeat = computed(() => route.value.stops.some(stop => isRepeat(stop.fields.SystemName)));
function add(repeat = false): void { selectedId.value = addWaypoint(route.value, repeat).id; }
function remove(): void {
  const index = selectedIndex.value;
  if (index < 0) return;
  route.value.stops.splice(index, 1);
  selectedId.value = route.value.stops[Math.min(index, route.value.stops.length - 1)]?.id ?? null;
}
</script>

<template>
  <fieldset class="route-editor" :disabled="busy">
    <legend class="sr-only">Waypoint route editor</legend>
    <div class="route-summary">
      <div class="route-stats" aria-label="Route summary">
        <span><strong>{{ route.stops.length }}</strong> stops</span>
        <span><strong>{{ stats.pending }}</strong> pending</span>
        <span><strong>{{ stats.completed }}</strong> completed</span>
        <span><strong>{{ stats.skipped }}</strong> skipped</span>
      </div>
      <div class="route-tools">
        <button class="btn btn-sm btn-outline" @click="add()">+ Add stop</button>
        <button class="btn btn-sm btn-outline" :disabled="hasRepeat" @click="add(true)">+ Repeat route</button>
        <button class="btn btn-sm btn-outline" :disabled="!route.stops.some(stop => stop.fields.Completed)" @click="route.stops.forEach(stop => stop.fields.Completed = false)">Reset completion</button>
      </div>
    </div>
    <p class="route-hint">Select a stop to edit it. The line shows travel order; badges reflect the file’s saved state.</p>
    <div class="route-workspace">
      <nav class="route-timeline" aria-label="Waypoint travel order">
        <ol v-if="route.stops.length">
          <li v-for="(stop, index) in route.stops" :key="stop.id" :class="{ skipped: stop.fields.Skip, completed: stop.fields.Completed }">
            <button class="route-stop" :class="{ selected: selectedId === stop.id }" :aria-current="selectedId === stop.id ? 'step' : undefined" @click="selectedId = stop.id">
              <span class="stop-number">{{ isRepeat(stop.fields.SystemName) ? '↻' : index + 1 }}</span>
              <span class="stop-info">
                <strong>{{ isRepeat(stop.fields.SystemName) ? 'Repeat route' : stop.fields.SystemName || stop.fields.StationName || (hasBookmark(stop.fields) ? 'Bookmark destination' : 'New destination') }}</strong>
                <span class="stop-station">{{ isRepeat(stop.fields.SystemName) ? 'Return to the first stop' : stop.fields.StationName || (hasBookmark(stop.fields) ? 'Bookmark destination' : 'System only') }}</span>
                <span class="stop-tags">
                  <span v-if="stop.fields.Skip" class="tag tag-muted">Skipped</span>
                  <span v-else-if="stop.fields.Completed" class="tag tag-green">Completed</span>
                  <span v-else class="tag">Pending</span>
                  <span v-if="!isRepeat(stop.fields.SystemName) && currentSystem !== 'Unknown' && currentSystem.toLowerCase() === stop.fields.SystemName.toLowerCase()" class="tag tag-cyan">Current system</span>
                  <span v-if="stop.buy.length || stop.sell.length" class="tag tag-muted">Trading</span>
                </span>
              </span>
            </button>
          </li>
        </ol>
        <div v-else class="empty-route">Your route is empty. Add a stop to start planning.</div>
      </nav>

      <div class="stop-editor">
        <template v-if="selected">
          <div class="stop-editor-heading">
            <h3>Stop {{ selectedIndex + 1 }} <span class="muted">/ {{ route.stops.length }}</span></h3>
            <div class="route-tools">
              <button class="btn btn-sm btn-outline" :disabled="selectedIndex === 0" aria-label="Move stop up" @click="moveWaypoint(route, selected.id, -1)">↑</button>
              <button class="btn btn-sm btn-outline" :disabled="selectedIndex === route.stops.length - 1" aria-label="Move stop down" @click="moveWaypoint(route, selected.id, 1)">↓</button>
              <button class="btn btn-sm btn-outline remove-stop" @click="remove">Remove stop</button>
            </div>
          </div>
          <div class="field-grid">
            <label>Waypoint name <input v-model="selected.key" autocomplete="off"></label>
            <label>System <input v-model="selected.fields.SystemName" placeholder="e.g. Eravate" autocomplete="off"></label>
            <label class="wide">Station <input v-model="selected.fields.StationName" placeholder="Optional — leave empty for system travel" autocomplete="off"></label>
            <label class="wide">Comment <textarea v-model="selected.fields.Comment" rows="2" placeholder="Notes for this stop"></textarea></label>
          </div>
          <p v-if="isRepeat(selected.fields.SystemName)" class="repeat-note">REPEAT restarts the route. Keep this stop at the end.</p>
          <div class="check-fields">
            <label><input v-model="selected.fields.Skip" type="checkbox"> Skip stop</label>
            <label><input v-model="selected.fields.Completed" type="checkbox"> Completed</label>
          </div>
          <div class="trade-grid">
            <CommodityEditor v-model="selected.buy" label="Buy" />
            <CommodityEditor v-model="selected.sell" label="Sell" />
          </div>
          <div class="check-fields">
            <label><input v-model="selected.fields.UpdateCommodityCount" type="checkbox"> Update commodity counts</label>
            <label><input v-model="selected.fields.FleetCarrierTransfer" type="checkbox"> Fleet carrier transfer</label>
          </div>
          <details class="advanced-fields">
            <summary>Bookmarks</summary>
            <p class="muted">Keep the type used by your in-game bookmarks. Number 0 or -1 disables a bookmark.</p>
            <div class="field-grid">
              <label>Galaxy bookmark type <input v-model="selected.fields.GalaxyBookmarkType" list="galaxy-bookmark-types" placeholder="None"></label>
              <label>Galaxy bookmark number <input v-model.number="selected.fields.GalaxyBookmarkNumber" type="number" min="-1" step="1"></label>
              <label>System bookmark type <input v-model="selected.fields.SystemBookmarkType" list="system-bookmark-types" placeholder="None"></label>
              <label>System bookmark number <input v-model.number="selected.fields.SystemBookmarkNumber" type="number" min="-1" step="1"></label>
            </div>
            <datalist id="galaxy-bookmark-types"><option>Fav</option><option>Sys</option><option>Bod</option><option>Sta</option><option>Set</option></datalist>
            <datalist id="system-bookmark-types"><option>Fav</option><option>Bod</option><option>Sta</option><option>Set</option><option>Nav</option></datalist>
          </details>
        </template>
        <p v-else class="empty-route">Add a destination to edit its details.</p>
      </div>
    </div>

    <details class="shopping-editor">
      <summary>Global shopping list <span class="muted">· {{ route.shopping.buy.length }} commodities</span></summary>
      <p class="muted">Purchases to look for throughout the route.</p>
      <div class="check-fields">
        <label><input v-model="route.shopping.fields.UpdateCommodityCount" type="checkbox"> Update commodity counts</label>
      </div>
      <CommodityEditor v-model="route.shopping.buy" label="Global buy" />
      <label class="shopping-comment">Comment <textarea v-model="route.shopping.fields.Comment" rows="2"></textarea></label>
    </details>
  </fieldset>
</template>

<style scoped>
.route-editor { border: 0; min-width: 0; margin: 20px 0 0; padding: 0; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.route-summary, .stop-editor-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.route-stats, .route-tools { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.route-stats { color: var(--text-muted); font-size: .85rem; }
.route-stats strong { color: var(--text-primary); font-size: 1.15rem; }
.route-hint, .muted { color: var(--text-muted); font-size: .85rem; }
.route-hint { margin: 12px 0; }
.route-workspace { display: grid; grid-template-columns: minmax(230px, .75fr) minmax(0, 2fr); border: 1px solid var(--border-color); border-radius: 10px; overflow: hidden; }
.route-timeline { background: var(--bg-secondary); padding: 16px; max-height: 620px; overflow-y: auto; }
.route-timeline ol { list-style: none; padding: 0; }
.route-timeline li { position: relative; padding-bottom: 14px; }
.route-timeline li:not(:last-child)::after { content: ''; position: absolute; width: 2px; background: var(--border-color); top: 37px; bottom: -17px; left: 27px; pointer-events: none; }
.route-stop { width: 100%; display: flex; align-items: flex-start; gap: 12px; border: 1px solid transparent; border-radius: 8px; text-align: left; padding: 10px; background: transparent; color: var(--text-primary); cursor: pointer; font: inherit; }
.route-stop:hover { background: var(--bg-card); }
.route-stop.selected { border-color: var(--accent-cyan); background: rgba(0,210,255,.06); }
.stop-number { flex: 0 0 32px; height: 32px; display: grid; place-items: center; border-radius: 50%; background: var(--bg-card); border: 2px solid var(--accent-orange); color: var(--accent-orange); font-family: var(--font-mono); font-size: .9rem; z-index: 1; }
.completed .stop-number { border-color: var(--accent-green); color: var(--accent-green); }
.skipped .stop-number { border-color: var(--text-muted); color: var(--text-muted); border-style: dashed; }
.stop-info { display: flex; flex-direction: column; min-width: 0; padding-top: 2px; gap: 3px; }
.stop-info strong { font-size: .95rem; overflow-wrap: anywhere; }
.stop-station { font-size: .8rem; color: var(--text-muted); overflow-wrap: anywhere; }
.stop-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.tag { font-size: .65rem; padding: 1px 6px; border: 1px solid var(--border-color); border-radius: 4px; color: var(--accent-orange); }
.tag-muted { color: var(--text-muted); }
.tag-green { color: var(--accent-green); }
.tag-cyan { color: var(--accent-cyan); }
.stop-editor { min-width: 0; padding: 20px; border-left: 1px solid var(--border-color); }
.stop-editor h3 { font-size: 1rem; }
.remove-stop { color: var(--accent-red); }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.wide { grid-column: 1 / -1; }
label { display: flex; flex-direction: column; gap: 5px; font-size: .85rem; color: var(--text-muted); }
input:not([type=checkbox]), textarea { width: 100%; min-width: 0; padding: 9px 10px; background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: 5px; color: var(--text-primary); font: inherit; }
input:focus, textarea:focus { outline: 1px solid var(--accent-cyan); }
textarea { resize: vertical; }
.check-fields { display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0; }
.check-fields label { flex-direction: row; align-items: center; gap: 7px; }
input[type=checkbox] { accent-color: var(--accent-cyan); }
.trade-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; margin-top: 20px; }
.advanced-fields, .shopping-editor { border-top: 1px solid var(--border-color); padding-top: 14px; margin-top: 20px; }
summary { cursor: pointer; font-size: .9rem; }
details[open] > summary { margin-bottom: 12px; }
.shopping-editor { padding: 16px; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 8px; }
.shopping-editor :deep(.commodities) { max-width: 620px; }
.shopping-comment { margin-top: 16px; max-width: 620px; }
.repeat-note { color: var(--accent-cyan); margin-top: 12px; font-size: .85rem; }
.empty-route { color: var(--text-muted); padding: 24px 12px; font-size: .9rem; }
button:focus-visible, summary:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 3px; }
@media (max-width: 900px) { .trade-grid { grid-template-columns: 1fr; gap: 16px; } }
@media (max-width: 640px) {
  .route-workspace { grid-template-columns: 1fr; }
  .route-timeline { max-height: 280px; }
  .stop-editor { border-left: 0; border-top: 1px solid var(--border-color); padding: 16px; }
  .field-grid { grid-template-columns: 1fr; }
  .route-tools { gap: 6px; }
}
</style>
