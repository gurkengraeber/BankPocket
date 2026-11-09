<script lang="ts">
  import { monatName } from '../lib/format';

  type Monat = { monat: string; einnahmen: number; ausgaben: number };
  // schmal: zwölf Monate eines Jahres nebeneinander
  let { daten, aktiv, onwahl, schmal = false }: { daten: Monat[]; aktiv?: string | null; onwahl?: (m: string) => void; schmal?: boolean } = $props();
  const max = $derived(Math.max(1, ...daten.flatMap((d) => [Number(d.einnahmen), Number(d.ausgaben)])));
</script>

<div class="flex h-40 items-end justify-between {schmal ? 'gap-0.5' : 'gap-1.5'}">
  {#each daten as d (d.monat)}
    <button
      class="flex flex-1 flex-col items-center gap-2 rounded-xl py-1 transition-colors {aktiv === d.monat ? 'bg-card-hi' : ''}"
      onclick={() => onwahl?.(d.monat)}
      aria-label="{monatName(d.monat)} anzeigen"
    >
      <div class="flex h-28 w-full items-end justify-center {schmal ? 'gap-0.5' : 'gap-1'}">
        <div class="{schmal ? 'w-1.5' : 'w-2.5'} rounded-full bg-pos transition-[height] duration-200" style="height: {Math.max(2, (Number(d.einnahmen) / max) * 100)}%"></div>
        <div class="{schmal ? 'w-1.5' : 'w-2.5'} rounded-full bg-neg transition-[height] duration-200" style="height: {Math.max(2, (Number(d.ausgaben) / max) * 100)}%"></div>
      </div>
      <span class="text-[11px] font-medium {aktiv === d.monat ? 'text-text' : 'text-muted'}">{schmal ? monatName(d.monat, true).slice(0, 1) : monatName(d.monat, true)}</span>
    </button>
  {/each}
</div>
