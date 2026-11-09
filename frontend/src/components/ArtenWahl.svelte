<script lang="ts">
  import { Plus, X } from '@lucide/svelte';

  // Mehrere Versicherungsarten für einen Vertrag: gewählte als Marken zum Wegtippen, weitere über die Auswahl
  let { arten, gewaehlt, vorschlag = '', onaendern }: { arten: string[]; gewaehlt: string[]; vorschlag?: string; onaendern: (liste: string[]) => void } =
    $props();
  const frei = $derived(arten.filter((a) => !gewaehlt.includes(a)));
</script>

<div class="flex flex-wrap items-center gap-1.5">
  {#each gewaehlt as a (a)}
    <span class="inline-flex items-center gap-1 rounded-full bg-accent-soft py-1 pl-3 pr-1.5 text-[13px] font-semibold text-accent">
      {a}
      <button type="button" class="grid size-5 place-items-center rounded-full active:bg-card-hi" onclick={() => onaendern(gewaehlt.filter((x) => x !== a))} aria-label="{a} entfernen"><X size={13} /></button>
    </span>
  {/each}
  {#if vorschlag && !gewaehlt.length}
    <button type="button" class="rounded-full border border-dashed border-accent px-3 py-1 text-[13px] font-semibold text-accent" onclick={() => onaendern([vorschlag])}>
      {vorschlag}? Übernehmen
    </button>
  {/if}
  <label class="relative inline-flex items-center gap-1 rounded-full bg-bg py-1 pl-2.5 pr-3 text-[13px] font-semibold text-muted">
    <Plus size={14} />{gewaehlt.length ? 'weitere' : 'Art wählen'}
    <select
      class="absolute inset-0 cursor-pointer appearance-none opacity-0"
      value=""
      onchange={(e) => { const v = e.currentTarget.value; e.currentTarget.value = ''; if (v) onaendern([...gewaehlt, v]); }}
      aria-label="Versicherungsart hinzufügen"
    >
      <option value="">Art wählen …</option>
      {#each frei as a (a)}<option value={a}>{a}</option>{/each}
    </select>
  </label>
</div>
