<script lang="ts">
  import { api } from '../lib/api';
  import { fehler, toast } from '../lib/store.svelte';
  import DatumFeld from './DatumFeld.svelte';
  import Sheet from './Sheet.svelte';

  let { offen = $bindable(false), konto, ongespeichert }: { offen: boolean; konto: { id: number; name: string } | null; ongespeichert?: () => void } =
    $props();

  let art = $state<'ausgabe' | 'einnahme'>('ausgabe');
  let betrag = $state('');
  let text = $state('');
  let tag = $state(new Date().toISOString().slice(0, 10));
  let speichert = $state(false);

  const zahl = $derived(Number(betrag.replace(/\./g, '').replace(',', '.')));

  async function speichern(e: SubmitEvent) {
    e.preventDefault();
    if (!konto || !(zahl > 0)) return;
    speichert = true;
    try {
      await api(`/accounts/${konto.id}/transactions`, {
        body: { datum: tag, betrag: (art === 'ausgabe' ? -zahl : zahl).toFixed(2), gegenpartei: text, verwendungszweck: '' },
      });
      toast('Buchung gespeichert');
      betrag = '';
      text = '';
      offen = false;
      ongespeichert?.();
    } catch (err) {
      fehler(err);
    } finally {
      speichert = false;
    }
  }
</script>

<Sheet bind:offen titel="Buchung hinzufügen">
  <form onsubmit={speichern} class="space-y-4">
    <p class="-mt-3 text-[15px] text-muted">{konto?.name}</p>
    <div class="grid grid-cols-2 gap-1 rounded-2xl bg-card p-1">
      {#each [['ausgabe', 'Ausgabe'], ['einnahme', 'Einnahme']] as [wert, label] (wert)}
        <button
          type="button"
          class="rounded-xl py-2.5 text-[15px] font-semibold transition-colors {art === wert ? 'bg-card-hi text-text' : 'text-muted'}"
          onclick={() => (art = wert as typeof art)}>{label}</button
        >
      {/each}
    </div>
    <div>
      <label class="label" for="b-betrag">Betrag</label>
      <div class="relative">
        <input id="b-betrag" class="feld pr-10 text-2xl font-semibold" inputmode="decimal" placeholder="0,00" bind:value={betrag} />
        <span class="absolute right-4 top-1/2 -translate-y-1/2 text-xl text-muted">€</span>
      </div>
    </div>
    <div>
      <label class="label" for="b-text">Beschreibung</label>
      <input id="b-text" class="feld" placeholder="z. B. Bäcker, Kaution Wohnung" bind:value={text} />
    </div>
    <div>
      <label class="label" for="b-datum">Datum</label>
      <DatumFeld id="b-datum" bind:wert={tag} />
    </div>
    <button class="knopf-primaer w-full" disabled={!(zahl > 0) || speichert}>Speichern</button>
  </form>
</Sheet>
