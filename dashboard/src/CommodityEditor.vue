<script setup lang="ts">
import { newCommodity, type CommodityDraft } from './waypointRoute';
const rows = defineModel<CommodityDraft[]>({ required: true });
defineProps<{ label: string }>();
</script>

<template>
  <div class="commodities">
    <div class="commodity-heading">
      <h4>{{ label }}</h4>
      <button type="button" class="btn btn-sm btn-outline" @click="rows.push(newCommodity())">Add commodity</button>
    </div>
    <p v-if="!rows.length" class="muted">No commodities.</p>
    <div v-for="(row, index) in rows" :key="row.id" class="commodity-row">
      <input v-model="row.name" :aria-label="`${label} commodity ${index + 1}`" placeholder="Commodity name">
      <input v-model.number="row.quantity" type="number" min="0" step="1" :aria-label="`${label} quantity ${index + 1}`">
      <button type="button" class="btn btn-sm btn-outline" :aria-label="`Remove ${label.toLowerCase()} commodity ${index + 1}`" @click="rows.splice(index, 1)">×</button>
    </div>
  </div>
</template>

<style scoped>
.commodity-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
h4 { font-size: .85rem; font-weight: 600; }
.commodity-row { display: grid; grid-template-columns: minmax(0, 1fr) 85px 34px; gap: 6px; margin-top: 6px; }
input { width: 100%; min-width: 0; padding: 8px; background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--border-color); border-radius: 5px; font: inherit; font-size: .85rem; }
input:focus { outline: 1px solid var(--accent-cyan); }
.muted { color: var(--text-muted); font-size: .85rem; }
</style>
