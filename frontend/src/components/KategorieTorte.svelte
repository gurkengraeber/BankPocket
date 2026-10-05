<script lang="ts">
  import { ChevronRight } from '@lucide/svelte';
  import { euro } from '../lib/format';
  import { ui } from '../lib/store.svelte';

  type Stueck = { kategorie: string; summe: number | string; anteil: number; farbe: string };
  let {
    stuecke,
    gesamt,
    titel = 'Ausgaben',
    wahl = $bindable(null),
    onwahl,
  }: { stuecke: Stueck[]; gesamt: number | string; titel?: string; wahl?: string | null; onwahl?: (kategorie: string) => void } = $props();

  // Antippen wählt ein Stück aus (Name und Summe stehen dann in der Mitte); erst der Knopf dort öffnet die Buchungen
  let schwebt = $state<string | null>(null);
  const r = 40;
  const umfang = 2 * Math.PI * r;

  // Jedes Stück ist ein Kreisbogen: Länge nach Anteil, versetzt um die Summe der vorherigen
  const boegen = $derived.by(() => {
    let start = 0;
    return stuecke.map((s) => {
      const bogen = { ...s, laenge: s.anteil * umfang, versatz: -start * umfang };
      start += s.anteil;
      return bogen;
    });
  });
  const fest = $derived(stuecke.find((s) => s.kategorie === wahl) ?? null);
  const gewaehlt = $derived(stuecke.find((s) => s.kategorie === schwebt) ?? fest);
  const aktiv = $derived(gewaehlt?.kategorie ?? null);
  const umschalten = (k: string) => (wahl = wahl === k ? null : k);
</script>

<div class="relative mx-auto size-56">
  <svg viewBox="0 0 100 100" class="size-full -rotate-90" role="img" aria-label="Ausgaben nach Kategorie als Tortendiagramm">
    {#each boegen as b (b.kategorie)}
      <circle
        cx="50"
        cy="50"
        {r}
        fill="none"
        stroke={b.farbe}
        stroke-width={aktiv === b.kategorie ? 17 : 14}
        stroke-dasharray="{Math.max(b.laenge - 0.6, 0.2)} {umfang}"
        stroke-dashoffset={b.versatz}
        class="cursor-pointer outline-none transition-[stroke-width,opacity] duration-150 [-webkit-tap-highlight-color:transparent] {aktiv && aktiv !== b.kategorie ? 'opacity-45' : ''}"
        role="button"
        tabindex="0"
        aria-label="{b.kategorie}: {Math.round(b.anteil * 100)} %"
        aria-pressed={wahl === b.kategorie}
        onpointerenter={(e) => e.pointerType === 'mouse' && (schwebt = b.kategorie)}
        onpointerleave={() => (schwebt = null)}
        onfocus={() => (schwebt = b.kategorie)}
        onblur={() => (schwebt = null)}
        onclick={() => umschalten(b.kategorie)}
        onkeydown={(e) => e.key === 'Enter' && umschalten(b.kategorie)}
      />
    {/each}
  </svg>
  <div class="pointer-events-none absolute inset-0 grid place-items-center text-center">
    <div class="max-w-[7.5rem]">
      <div class="truncate text-[12px] text-muted">{gewaehlt ? gewaehlt.kategorie : titel}</div>
      <div class="text-[20px] font-bold tracking-tight tabular-nums {ui.versteckt ? 'versteckt' : ''}">
        {euro(gewaehlt ? gewaehlt.summe : gesamt, { kurz: true })}
      </div>
      {#if gewaehlt}<div class="text-[12px] text-muted">{Math.round(gewaehlt.anteil * 100)} %</div>{/if}
      {#if onwahl && fest && gewaehlt === fest}
        <button class="pointer-events-auto mt-1 inline-flex items-center text-[12px] font-semibold text-accent" onclick={() => onwahl(fest.kategorie)}>
          Buchungen <ChevronRight size={14} />
        </button>
      {/if}
    </div>
  </div>
</div>
