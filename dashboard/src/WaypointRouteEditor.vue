<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import CommodityEditor from './CommodityEditor.vue';
import { addWaypoint, moveWaypoint, moveWaypoints, removeWaypoints, restoreWaypoints, type WaypointRoute, type RemovedWaypoint } from './waypointRoute';

const route = defineModel<WaypointRoute>({ required: true });
defineProps<{ busy: boolean; currentSystem: string }>();
const selectedId = ref<number | null>(null);
const checkedIds = ref(new Set<number>());
const anchorId = ref<number | null>(null);
const activeRowId = ref<number | null>(null);
const view = ref<'table' | 'route'>('table');
const detailsOpen = ref(false);
const search = ref('');
const statusFilter = ref('all');
const editor = ref<HTMLElement | null>(null);
const detailsHeading = ref<HTMLElement | null>(null);
const announcement = ref('');
const lastRemoval = ref<{ entries: RemovedWaypoint[]; activeId: number | null } | null>(null);
watch(() => route.value.id, () => {
  selectedId.value = route.value.stops[0]?.id ?? null;
  clearSelection();
  activeRowId.value = null;
  detailsOpen.value = false;
  search.value = '';
  statusFilter.value = 'all';
  lastRemoval.value = null;
  announcement.value = '';
}, { immediate: true });
const selected = computed(() => route.value.stops.find(stop => stop.id === selectedId.value));
const selectedIndex = computed(() => route.value.stops.findIndex(stop => stop.id === selectedId.value));
const visibleRows = computed(() => {
  const query = search.value.trim().toLowerCase();
  return route.value.stops.map((stop, index) => ({ stop, index })).filter(({ stop }) => {
    // Keep a row in place while editing, even when its new value no longer matches.
    if (activeRowId.value === stop.id) return true;
    const matchesText = !query || [stop.key, stop.fields.SystemName, stop.fields.StationName, stop.fields.Comment ?? '']
      .some(value => value.toLowerCase().includes(query));
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'skipped' && stop.fields.Skip)
      || (statusFilter.value === 'completed' && stop.fields.Completed && !stop.fields.Skip)
      || (statusFilter.value === 'pending' && !stop.fields.Skip && !stop.fields.Completed);
    return matchesText && matchesStatus;
  });
});
const allVisibleChecked = computed(() => visibleRows.value.length > 0 && visibleRows.value.every(({ stop }) => checkedIds.value.has(stop.id)));
const visibleCheckedCount = computed(() => visibleRows.value.filter(({ stop }) => checkedIds.value.has(stop.id)).length);
const someVisibleChecked = computed(() => visibleCheckedCount.value > 0 && !allVisibleChecked.value);
const hiddenCheckedCount = computed(() => checkedIds.value.size - visibleCheckedCount.value);
const visibleDetailIndex = computed(() => visibleRows.value.findIndex(({ stop }) => stop.id === selectedId.value));
const canMoveUp = computed(() => route.value.stops.some((stop, index) => checkedIds.value.has(stop.id) && index > 0 && !checkedIds.value.has(route.value.stops[index - 1].id)));
const canMoveDown = computed(() => route.value.stops.some((stop, index) => checkedIds.value.has(stop.id) && index < route.value.stops.length - 1 && !checkedIds.value.has(route.value.stops[index + 1].id)));
watch([search, statusFilter], () => {
  activeRowId.value = null;
  anchorId.value = null;
  if (view.value === 'table') detailsOpen.value = false;
  if (!visibleRows.value.some(({ stop }) => stop.id === selectedId.value)) selectedId.value = visibleRows.value[0]?.stop.id ?? null;
});
const stats = computed(() => ({
  skipped: route.value.stops.filter(stop => stop.fields.Skip).length,
  completed: route.value.stops.filter(stop => stop.fields.Completed && !stop.fields.Skip).length,
  pending: route.value.stops.filter(stop => !stop.fields.Skip && !stop.fields.Completed && !isRepeat(stop.fields.SystemName)).length
}));
const isRepeat = (name: string) => name.trim().toUpperCase() === 'REPEAT';
const hasBookmark = (fields: WaypointRoute['stops'][number]['fields']) => fields.GalaxyBookmarkNumber > 0 || fields.SystemBookmarkNumber > 0;
const hasRepeat = computed(() => route.value.stops.some(stop => isRepeat(stop.fields.SystemName)));
function clearSelection(): void { checkedIds.value = new Set(); anchorId.value = null; }
function toggleRow(event: MouseEvent, id: number): void {
  const checked = (event.target as HTMLInputElement).checked;
  const ids = visibleRows.value.map(({ stop }) => stop.id);
  const anchor = anchorId.value === null ? -1 : ids.indexOf(anchorId.value);
  const target = ids.indexOf(id);
  const range = event.shiftKey && anchor >= 0 && target >= 0
    ? ids.slice(Math.min(anchor, target), Math.max(anchor, target) + 1) : [id];
  const updated = new Set(checkedIds.value);
  for (const value of range) { if (checked) updated.add(value); else updated.delete(value); }
  checkedIds.value = updated;
  anchorId.value = id;
}
function toggleAll(event: Event): void {
  const checked = (event.target as HTMLInputElement).checked;
  const updated = new Set(checkedIds.value);
  for (const { stop } of visibleRows.value) { if (checked) updated.add(stop.id); else updated.delete(stop.id); }
  checkedIds.value = updated;
  anchorId.value = null;
}
function setSelectedFlag(field: 'Skip' | 'Completed', value: boolean): void {
  for (const stop of route.value.stops) if (checkedIds.value.has(stop.id)) stop.fields[field] = value;
  announcement.value = `Updated ${checkedIds.value.size} selected stops.`;
}
function moveSelected(direction: -1 | 1): void {
  moveWaypoints(route.value, checkedIds.value, direction);
  announcement.value = `Moved ${checkedIds.value.size} selected stops ${direction === -1 ? 'up' : 'down'}.`;
}
function leaveRow(event: FocusEvent): void {
  if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null)) activeRowId.value = null;
}
function focusField(id: number, field: string): HTMLInputElement | undefined {
  const input = editor.value?.querySelector<HTMLInputElement>(`[data-stop-id="${id}"] [data-field="${field}"]`);
  input?.focus();
  return input ?? undefined;
}
function nextField(id: number, field: string, direction: number): void {
  const index = visibleRows.value.findIndex(({ stop }) => stop.id === id);
  const next = visibleRows.value[index + direction];
  if (next) focusField(next.stop.id, field)?.select();
}
async function openDetails(id: number): Promise<void> {
  selectedId.value = id;
  detailsOpen.value = true;
  await nextTick();
  detailsHeading.value?.focus({ preventScroll: true });
  detailsHeading.value?.scrollIntoView({ block: 'nearest' });
}
function stepDetails(direction: number): void {
  const next = visibleRows.value[visibleDetailIndex.value + direction];
  if (next) openDetails(next.stop.id);
}
async function add(repeat = false): Promise<void> {
  search.value = '';
  statusFilter.value = 'all';
  clearSelection();
  const stop = addWaypoint(route.value, repeat);
  await nextTick();
  selectedId.value = stop.id;
  if (view.value === 'table') {
    detailsOpen.value = false;
    await nextTick();
    focusField(stop.id, 'SystemName');
  } else {
    await nextTick();
    editor.value?.querySelector<HTMLInputElement>('[data-detail-system]')?.focus();
  }
}
function remove(ids = new Set(selectedId.value === null ? [] : [selectedId.value])): void {
  const index = selectedIndex.value;
  const entries = removeWaypoints(route.value, ids);
  if (!entries.length) return;
  lastRemoval.value = { entries, activeId: selectedId.value };
  checkedIds.value = new Set([...checkedIds.value].filter(id => !ids.has(id)));
  anchorId.value = null;
  activeRowId.value = null;
  if (!route.value.stops.some(stop => stop.id === selectedId.value)) {
    selectedId.value = route.value.stops[Math.min(Math.max(index, 0), route.value.stops.length - 1)]?.id ?? null;
  }
  announcement.value = '';
}
function undoRemoval(): void {
  if (!lastRemoval.value) return;
  const { entries, activeId } = lastRemoval.value;
  const renamed = restoreWaypoints(route.value, entries);
  checkedIds.value = new Set(entries.map(entry => entry.stop.id));
  selectedId.value = activeId ?? entries[0].stop.id;
  lastRemoval.value = null;
  announcement.value = `Restored ${entries.length} stops. Other edits were kept.${renamed ? ` ${renamed} restored waypoint names were made unique.` : ''}`;
}
</script>

<template>
  <fieldset ref="editor" class="route-editor" :disabled="busy">
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
    <div class="route-filter-bar">
      <input v-model="search" type="search" aria-label="Search waypoints" placeholder="Search system, station, name or comment…">
      <select v-model="statusFilter" aria-label="Filter waypoint status">
        <option value="all">All stops</option><option value="pending">Pending</option><option value="completed">Completed</option><option value="skipped">Skipped</option>
      </select>
      <span class="muted">{{ visibleRows.length }} of {{ route.stops.length }} shown</span>
      <button v-if="search || statusFilter !== 'all'" class="btn btn-sm btn-outline" @click="search = ''; statusFilter = 'all'">Clear filters</button>
      <div class="view-switch" role="group" aria-label="Waypoint view">
        <button class="btn btn-sm btn-outline" :aria-pressed="view === 'table'" @click="view = 'table'">Quick edit</button>
        <button class="btn btn-sm btn-outline" :aria-pressed="view === 'route'" @click="view = 'route'">Route view</button>
      </div>
    </div>
    <div class="selection-bar">
      <label class="select-all"><input type="checkbox" :checked="allVisibleChecked" :indeterminate="someVisibleChecked" :disabled="!visibleRows.length" @change="toggleAll"> Select all shown</label>
      <span class="selection-count">{{ checkedIds.size }} selected<span v-if="hiddenCheckedCount"> · {{ hiddenCheckedCount }} outside filter</span></span>
      <button class="btn btn-sm btn-outline" :disabled="!checkedIds.size" @click="clearSelection">Clear selection</button>
      <div class="bulk-actions" aria-label="Actions for selected waypoints">
        <button class="btn btn-sm btn-danger" :disabled="!checkedIds.size" @click="remove(checkedIds)">Delete selected ({{ checkedIds.size }})</button>
        <button class="btn btn-sm btn-outline" :disabled="!checkedIds.size" @click="setSelectedFlag('Skip', true)">Skip selected</button>
        <button class="btn btn-sm btn-outline" :disabled="!checkedIds.size" @click="setSelectedFlag('Skip', false)">Enable selected</button>
        <button class="btn btn-sm btn-outline" :disabled="!checkedIds.size" @click="setSelectedFlag('Completed', true)">Mark completed</button>
        <button class="btn btn-sm btn-outline" :disabled="!checkedIds.size" @click="setSelectedFlag('Completed', false)">Mark pending</button>
        <button class="btn btn-sm btn-outline" :disabled="!canMoveUp" aria-label="Move selected up" @click="moveSelected(-1)">↑</button>
        <button class="btn btn-sm btn-outline" :disabled="!canMoveDown" aria-label="Move selected down" @click="moveSelected(1)">↓</button>
      </div>
    </div>
    <div v-if="lastRemoval" class="removal-notice" role="status">
      <span>Removed {{ lastRemoval.entries.length }} {{ lastRemoval.entries.length === 1 ? 'stop' : 'stops' }}.</span>
      <button class="btn btn-sm btn-outline" @click="undoRemoval">Undo removal</button>
    </div>
    <p class="route-hint">{{ view === 'table' ? 'Edit cells directly. Enter moves to the next stop in that column; Shift+Enter moves back.' : 'Select a stop for details. The line shows travel order.' }} Shift-click checkboxes to select a range.</p>
    <p v-if="announcement" class="edit-announcement" role="status">{{ announcement }}</p>
    <div class="route-workspace" :class="{ 'quick-workspace': view === 'table' }">
      <div v-if="view === 'table'" class="quick-table-wrap" role="region" aria-label="Quick edit waypoints" tabindex="0">
        <table class="quick-table">
          <caption class="sr-only">Waypoints in travel order. Edit cells or select rows for bulk actions.</caption>
          <thead><tr><th scope="col"><span class="sr-only">Select</span></th><th scope="col">#</th><th scope="col">Name</th><th scope="col">System</th><th scope="col">Station</th><th scope="col">Skip</th><th scope="col">Done</th><th scope="col">Actions</th></tr></thead>
          <tbody>
            <tr v-for="{ stop, index } in visibleRows" :key="stop.id" :data-stop-id="stop.id" :class="{ checked: checkedIds.has(stop.id), inspected: detailsOpen && selectedId === stop.id }" @focusin="activeRowId = stop.id" @focusout="leaveRow">
              <td><label class="row-check-hit"><input class="row-select" type="checkbox" :aria-label="`Select stop ${index + 1}: ${stop.fields.SystemName || stop.fields.StationName || stop.key}`" :checked="checkedIds.has(stop.id)" @click="toggleRow($event, stop.id)"></label></td>
              <td class="row-number">{{ isRepeat(stop.fields.SystemName) ? '↻' : index + 1 }}</td>
              <td><input v-model="stop.key" data-field="key" :aria-label="`Waypoint name for stop ${index + 1}`" autocomplete="off" @keydown.enter.prevent="nextField(stop.id, 'key', $event.shiftKey ? -1 : 1)"></td>
              <td><input v-model="stop.fields.SystemName" data-field="SystemName" :aria-label="`System for stop ${index + 1}`" placeholder="System" autocomplete="off" @keydown.enter.prevent="nextField(stop.id, 'SystemName', $event.shiftKey ? -1 : 1)"><span v-if="!isRepeat(stop.fields.SystemName) && currentSystem !== 'Unknown' && currentSystem.toLowerCase() === stop.fields.SystemName.toLowerCase()" class="tag tag-cyan">Current system</span></td>
              <td><input v-model="stop.fields.StationName" data-field="StationName" :aria-label="`Station for stop ${index + 1}`" placeholder="Optional" autocomplete="off" @keydown.enter.prevent="nextField(stop.id, 'StationName', $event.shiftKey ? -1 : 1)"></td>
              <td><input v-model="stop.fields.Skip" type="checkbox" :aria-label="`Skip stop ${index + 1}`"></td>
              <td><input v-model="stop.fields.Completed" type="checkbox" :aria-label="`Completed stop ${index + 1}`"></td>
              <td><div class="row-actions"><button class="btn btn-sm btn-outline" :aria-label="`Details for stop ${index + 1}`" @click="openDetails(stop.id)">Details<span v-if="stop.buy.length || stop.sell.length"> · Trade</span></button><button class="btn btn-sm btn-outline remove-stop" :aria-label="`Delete stop ${index + 1}`" @click="remove(new Set([stop.id]))">×</button></div></td>
            </tr>
            <tr v-if="!visibleRows.length"><td colspan="8" class="empty-route">{{ route.stops.length ? 'No matching waypoints. Clear the filters to see all stops.' : 'Your route is empty. Add a stop to start planning.' }}</td></tr>
          </tbody>
        </table>
      </div>
      <nav v-else class="route-timeline" aria-label="Waypoint travel order">
        <ol v-if="route.stops.length">
          <li v-for="{ stop, index } in visibleRows" :key="stop.id" :class="{ skipped: stop.fields.Skip, completed: stop.fields.Completed }">
            <input class="timeline-select" type="checkbox" :aria-label="`Select stop ${index + 1}: ${stop.fields.SystemName || stop.fields.StationName || stop.key}`" :checked="checkedIds.has(stop.id)" @click="toggleRow($event, stop.id)">
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
        <p v-if="route.stops.length && !visibleRows.length" class="empty-route">No matching waypoints. Clear the filters to see all stops.</p>
      </nav>

      <div v-if="view === 'route' || detailsOpen" class="stop-editor">
        <template v-if="selected">
          <div class="stop-editor-heading">
            <h3 ref="detailsHeading" tabindex="-1">Stop {{ selectedIndex + 1 }} <span class="muted">/ {{ route.stops.length }}</span></h3>
            <div class="route-tools">
              <button class="btn btn-sm btn-outline" :disabled="visibleDetailIndex <= 0" aria-label="Previous stop" @click="stepDetails(-1)">←</button>
              <button class="btn btn-sm btn-outline" :disabled="visibleDetailIndex < 0 || visibleDetailIndex === visibleRows.length - 1" aria-label="Next stop" @click="stepDetails(1)">→</button>
              <button class="btn btn-sm btn-outline" :disabled="selectedIndex === 0" aria-label="Move stop up" @click="moveWaypoint(route, selected.id, -1)">↑</button>
              <button class="btn btn-sm btn-outline" :disabled="selectedIndex === route.stops.length - 1" aria-label="Move stop down" @click="moveWaypoint(route, selected.id, 1)">↓</button>
              <button class="btn btn-sm btn-outline remove-stop" @click="remove()">Remove stop</button>
              <button v-if="view === 'table'" class="btn btn-sm btn-outline" @click="detailsOpen = false">Close details</button>
            </div>
          </div>
          <div class="field-grid">
            <label>Waypoint name <input v-model="selected.key" autocomplete="off"></label>
            <label>System <input v-model="selected.fields.SystemName" data-detail-system placeholder="e.g. Eravate" autocomplete="off"></label>
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
.route-filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
.route-filter-bar > input { flex: 1 1 230px; width: auto; }
.route-filter-bar select { padding: 9px; background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border-color); border-radius: 5px; font: inherit; font-size: .85rem; }
.view-switch { display: flex; gap: 4px; margin-left: auto; }
.view-switch [aria-pressed=true] { color: var(--accent-cyan); border-color: var(--accent-cyan); background: rgba(0,210,255,.08); }
.selection-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 0; min-height: 50px; }
.select-all { flex-direction: row; align-items: center; cursor: pointer; gap: 8px; }
.selection-count { color: var(--accent-cyan); font-size: .85rem; }
.selection-count > span { color: var(--accent-orange); }
.bulk-actions { display: flex; flex-basis: 100%; align-items: center; gap: 8px; flex-wrap: wrap; }
.removal-notice { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; background: rgba(0,210,255,.06); border: 1px solid var(--border-color); border-radius: 6px; padding: 10px 12px; font-size: .85rem; }
.edit-announcement { color: var(--accent-cyan); font-size: .85rem; margin: 8px 0; }
.route-workspace { display: grid; grid-template-columns: minmax(230px, .75fr) minmax(0, 2fr); border: 1px solid var(--border-color); border-radius: 10px; overflow: hidden; }
.route-workspace.quick-workspace { grid-template-columns: minmax(0, 1fr); }
.quick-table-wrap { min-width: 0; max-height: 520px; overflow: auto; }
.quick-table { border-collapse: separate; border-spacing: 0; width: 100%; min-width: 840px; font-size: .85rem; }
.quick-table th { position: sticky; top: 0; z-index: 1; background: var(--bg-secondary); color: var(--text-muted); text-align: left; font-size: .75rem; font-weight: 500; border-bottom: 1px solid var(--border-color); padding: 10px; }
.quick-table td { border-bottom: 1px solid var(--border-color); padding: 6px; }
.quick-table tr:last-child td { border-bottom: 0; }
.quick-table th:nth-child(1) { width: 42px; }
.quick-table th:nth-child(2) { width: 40px; }
.quick-table th:nth-child(3) { width: 105px; }
.quick-table th:nth-child(4), .quick-table th:nth-child(5) { width: 24%; }
.quick-table tr.checked { background: rgba(0,210,255,.06); }
.quick-table tr.inspected td:first-child { box-shadow: inset 3px 0 var(--accent-cyan); }
.quick-table input:not([type=checkbox]) { background: transparent; border-color: transparent; padding: 8px; height: 36px; }
.quick-table tr:hover input:not([type=checkbox]), .quick-table input:not([type=checkbox]):focus { background: var(--bg-primary); border-color: var(--border-color); }
.quick-table .row-check-hit { display: grid; place-items: center; padding: 8px 3px; cursor: pointer; }
.row-select, .timeline-select { width: 18px; height: 18px; cursor: pointer; }
.quick-table td:nth-child(6), .quick-table td:nth-child(7) { text-align: center; }
.row-number { color: var(--accent-orange); font-family: var(--font-mono); text-align: center; }
.row-actions { display: flex; gap: 5px; white-space: nowrap; }
.quick-workspace .stop-editor { border-left: 0; border-top: 1px solid var(--border-color); }
.route-timeline { background: var(--bg-secondary); padding: 16px; max-height: 620px; overflow-y: auto; }
.route-timeline ol { list-style: none; padding: 0; }
.route-timeline li { position: relative; display: flex; align-items: flex-start; gap: 8px; padding-bottom: 14px; }
.timeline-select { flex-shrink: 0; margin-top: 18px; }
.route-timeline li:not(:last-child)::after { content: ''; position: absolute; width: 2px; background: var(--border-color); top: 37px; bottom: -17px; left: 53px; pointer-events: none; }
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
  .route-filter-bar > input { flex-basis: 100%; }
  .view-switch { margin-left: 0; }
  .route-workspace { grid-template-columns: 1fr; }
  .route-timeline { max-height: 280px; }
  .stop-editor { border-left: 0; border-top: 1px solid var(--border-color); padding: 16px; }
  .field-grid { grid-template-columns: 1fr; }
  .route-tools { gap: 6px; }
}
</style>
