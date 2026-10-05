<script lang="ts">
  import { api } from '../lib/api';
  import { TURNUS } from '../lib/format';
  import { emoji } from '../lib/kategorien';
  import { fehler, toast } from '../lib/store.svelte';
  import Auswahl from './Auswahl.svelte';
  import DatumFeld from './DatumFeld.svelte';
  import KategorieWahl from './KategorieWahl.svelte';
  import { kategorieNeu, kategorienLaden } from '../lib/kategorieNeu';
  import Sheet from './Sheet.svelte';

  // kategorieVorgabe: z. B. „Versicherung“, wenn der Vertrag aus der Versicherungsübersicht angelegt wird
  // artVorgabe: Versicherungsart, die gleich mit eingetragen wird (z. B. aus der Merkliste „nicht erfasst“)
  let { offen = $bindable(false), ongespeichert, kategorieVorgabe = null, artVorgabe = '' }: { offen: boolean; ongespeichert?: () => void; kategorieVorgabe?: string | null; artVorgabe?: string } = $props();

  let art = $state<'ausgabe' | 'einnahme'>('ausgabe');
  let name = $state('');
  let betrag = $state('');
  let turnus = $state('monatlich');
  let kategorie = $state('Sonstiges');
  let faellig = $state(new Date().toISOString().slice(0, 10));
  let kategorien = $state<{ ausgabe: string[]; einnahme: string[] }>({ ausgabe: ['Sonstiges'], einnahme: ['Sonstige Einnahmen'] });

  $effect(() => {
    if (offen) kategorienLaden().then((k) => (kategorien = k));
  });
  $effect(() => {
    if (offen && artVorgabe && !name) name = artVorgabe;
  });
  $effect(() => {
    kategorie = art === 'ausgabe' ? (kategorieVorgabe ?? 'Sonstiges') : 'Sonstige Einnahmen';
  });

  const zahl = $derived(Number(betrag.replace(/\./g, '').replace(',', '.')));

  async function speichern(e: SubmitEvent) {
    e.preventDefault();
    try {
      const neu = await api('/contracts', {
        body: { name, kategorie, turnus, betrag: (art === 'ausgabe' ? -zahl : zahl).toFixed(2), naechste_faelligkeit: faellig },
      });
      if (artVorgabe) await api(`/contracts/${neu.id}`, { method: 'PATCH', body: { art: artVorgabe } });
      toast('Vertrag hinzugefügt');
      name = '';
      betrag = '';
      offen = false;
      ongespeichert?.();
    } catch (err) {
      fehler(err);
    }
  }
</script>

<Sheet bind:offen titel="Vertrag hinzufügen">
  <form onsubmit={speichern} class="space-y-4">
    <div class="grid grid-cols-2 gap-1 rounded-2xl bg-card p-1">
      {#each [['ausgabe', 'Ausgabe'], ['einnahme', 'Einnahme']] as [wert, label] (wert)}
        <button type="button" class="rounded-xl py-2.5 text-[15px] font-semibold {art === wert ? 'bg-card-hi' : 'text-muted'}" onclick={() => (art = wert as typeof art)}>{label}</button>
      {/each}
    </div>
    <div><label class="label" for="v-name">Name</label><input id="v-name" class="feld" placeholder="z. B. Hausratversicherung" bind:value={name} /></div>
    <div><label class="label" for="v-betrag">Betrag</label><input id="v-betrag" class="feld" inputmode="decimal" placeholder="0,00 €" bind:value={betrag} /></div>
    <div>
      <div class="label">Wie oft?</div>
      <Auswahl optionen={Object.entries(TURNUS)} bind:wert={turnus} />
    </div>
    <div>
      <label class="label" for="v-kat">Kategorie</label>
      <KategorieWahl id="v-kat" wert={kategorie} optionen={kategorien[art]} onwahl={(k) => (kategorie = k)}
        onneu={async (n) => { try { kategorien = await kategorieNeu(n, art); kategorie = n; } catch (err) { fehler(err); } }} />
    </div>
    <div><label class="label" for="v-datum">Nächste Fälligkeit</label><DatumFeld id="v-datum" bind:wert={faellig} /></div>
    <button class="knopf-primaer w-full" disabled={!name || !(zahl > 0)}>Speichern</button>
  </form>
</Sheet>
