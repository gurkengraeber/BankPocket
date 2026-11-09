<script lang="ts">
  import { Check } from '@lucide/svelte';
  import { api } from '../lib/api';
  import { emoji, oberVon, SYMBOLE } from '../lib/kategorien';
  import { euro } from '../lib/format';
  import { fehler, toast } from '../lib/store.svelte';
  import Sheet from './Sheet.svelte';

  // Bereich anlegen oder ändern: Name, Symbol, welche Kategorien und welche einzelnen Verträge dazugehören
  let { offen = $bindable(false), bereich = null, ongespeichert }: { offen: boolean; bereich?: any; ongespeichert?: (id: number) => void } = $props();

  let name = $state('');
  let symbol = $state('🏡');
  let kategorien = $state<string[]>([]);
  let vertraege = $state<number[]>([]);
  let alleKategorien = $state<string[]>([]);
  let alleVertraege = $state<any[]>([]);

  $effect(() => {
    if (!offen) return;
    name = bereich?.name ?? '';
    symbol = bereich?.emoji ?? '🏡';
    kategorien = [...(bereich?.kategorien ?? [])];
    vertraege = [...(bereich?.vertraege ?? [])];
    api('/kategorien').then((k) => (alleKategorien = [...new Set<string>([...k.ausgabe, ...k.einnahme])].filter((x) => !['Sonstiges', 'Sonstige Einnahmen', 'Sparen'].includes(x))));
    api('/contracts').then((c) => (alleVertraege = c.ausgaben.flatMap((s: any) => s.vertraege)));
  });

  const um = <T,>(liste: T[], x: T) => (liste.includes(x) ? liste.filter((y) => y !== x) : [...liste, x]);
  // ein Vertrag, dessen Kategorie schon gewählt ist, zählt ohnehin mit
  const schonDrin = (c: any) => kategorien.includes(c.kategorie) || kategorien.includes(oberVon[c.kategorie]);

  async function speichern(e: SubmitEvent) {
    e.preventDefault();
    try {
      const body = { name, emoji: symbol, kategorien, vertraege };
      const r = bereich?.id ? await api(`/bereiche/${bereich.id}`, { method: 'PUT', body }) : await api('/bereiche', { body });
      toast('Gespeichert');
      offen = false;
      ongespeichert?.(r.id);
    } catch (err) {
      fehler(err);
    }
  }
</script>

<Sheet bind:offen titel={bereich?.id ? 'Bereich ändern' : 'Neuer Bereich'}>
  <form class="space-y-5" onsubmit={speichern}>
    <div class="flex items-center gap-3">
      <span class="grid size-12 shrink-0 place-items-center rounded-[14px] bg-card-hi text-[24px]">{symbol}</span>
      <input class="feld min-w-0 flex-1" placeholder="z. B. Wohnung" bind:value={name} maxlength="40" aria-label="Name des Bereichs" />
    </div>
    <div>
      <div class="label">Symbol</div>
      <div class="flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none]" data-kein-wischen>
        {#each ['🏡', '🚗', '🚐', '💊', '🎓', '👶', '🐾', '✈️', '🎮', '💼', ...SYMBOLE.slice(0, 30)] as s, i (i)}
          <button type="button" class="grid size-10 shrink-0 place-items-center rounded-xl text-[20px] {symbol === s ? 'bg-accent-soft ring-2 ring-accent' : 'bg-card-hi'}" onclick={() => (symbol = s)} aria-label="Symbol {s}">{s}</button>
        {/each}
      </div>
    </div>
    <div>
      <div class="label">Kategorien, die dazugehören</div>
      <div class="flex flex-wrap gap-1.5">
        {#each alleKategorien as k (k)}
          <button type="button" class="rounded-full px-3 py-1.5 text-[14px] font-semibold {kategorien.includes(k) ? 'bg-accent text-white' : 'bg-card-hi text-muted'}" aria-pressed={kategorien.includes(k)} onclick={() => (kategorien = um(kategorien, k))}>
            {emoji(k)} {k}
          </button>
        {/each}
      </div>
      <p class="mt-1.5 text-[13px] text-muted">Alle Ausgaben dieser Kategorien zählen mit. Einnahmen darin (z. B. Untermiete) mindern die Kosten.</p>
    </div>
    <div>
      <div class="label">Einzelne Verträge dazu</div>
      <div class="karte max-h-64 divide-y divide-line overflow-y-auto">
        {#each alleVertraege as c (c.id)}
          {@const drin = schonDrin(c)}
          <button type="button" class="flex w-full items-center gap-3 px-3.5 py-2.5 text-left text-[15px] {drin ? 'opacity-60' : ''}" disabled={drin} onclick={() => (vertraege = um(vertraege, c.id))} aria-pressed={drin || vertraege.includes(c.id)}>
            <span class="grid size-6 shrink-0 place-items-center rounded-md border {drin || vertraege.includes(c.id) ? 'border-accent bg-accent text-white' : 'border-line'}">
              {#if drin || vertraege.includes(c.id)}<Check size={15} />{/if}
            </span>
            <span class="min-w-0 flex-1"><span class="block truncate">{c.name}</span><span class="block truncate text-[12px] text-muted">{c.kategorie}{drin ? ' · über die Kategorie dabei' : ''}</span></span>
            <span class="shrink-0 text-[13px] text-muted">{euro(c.monatlich, { kurz: true })} / Monat</span>
          </button>
        {:else}
          <div class="px-4 py-3 text-[14px] text-muted">Noch keine bestätigten Verträge.</div>
        {/each}
      </div>
    </div>
    <button class="knopf-primaer w-full" disabled={!name.trim() || (!kategorien.length && !vertraege.length)}>Speichern</button>
  </form>
</Sheet>
