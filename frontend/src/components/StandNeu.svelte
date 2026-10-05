<script lang="ts">
  import { api } from '../lib/api';
  import { fehler, toast } from '../lib/store.svelte';
  import DatumFeld from './DatumFeld.svelte';
  import Sheet from './Sheet.svelte';

  let { offen = $bindable(false), konto, ongespeichert }: { offen: boolean; konto: { id: number; name: string; saldo?: number | null; typ?: string } | null; ongespeichert?: () => void } =
    $props();

  let art = $state<'plus' | 'minus'>('plus');
  let betrag = $state('');
  let speichert = $state(false);
  const heute = new Date().toISOString().slice(0, 10);
  let tag = $state(heute);

  const zahl = $derived(Number(betrag.replace(/\./g, '').replace(',', '.')));

  // Beim Öffnen den bisherigen Stand vorbelegen
  $effect(() => {
    if (!offen) return;
    const s = Number(konto?.saldo ?? 0);
    art = s < 0 ? 'minus' : 'plus';
    betrag = s ? Math.abs(s).toFixed(2).replace('.', ',') : '';
  });

  async function speichern(e: SubmitEvent) {
    e.preventDefault();
    if (!konto || !(zahl >= 0)) return;
    speichert = true;
    try {
      await api(`/accounts/${konto.id}/stand`, { body: { saldo: (art === 'minus' ? -zahl : zahl).toFixed(2), datum: tag || heute } });
      toast('Stand gespeichert');
      offen = false;
      ongespeichert?.();
    } catch (err) {
      fehler(err);
    } finally {
      speichert = false;
    }
  }
</script>

<Sheet bind:offen titel="Stand eintragen">
  <form onsubmit={speichern} class="space-y-4">
    <p class="-mt-3 text-[15px] text-muted">{konto?.name}</p>
    <div class="grid grid-cols-2 gap-1 rounded-2xl bg-card p-1">
      {#each konto?.typ === 'virtuell' ? [['plus', 'Ich bekomme'], ['minus', 'Ich schulde']] : [['plus', 'Guthaben'], ['minus', 'Im Minus']] as [wert, label] (wert)}
        <button
          type="button"
          class="rounded-xl py-2.5 text-[15px] font-semibold transition-colors {art === wert ? 'bg-card-hi text-text' : 'text-muted'}"
          onclick={() => (art = wert as typeof art)}>{label}</button
        >
      {/each}
    </div>
    <div>
      <label class="label" for="s-betrag">Aktueller Stand</label>
      <div class="relative">
        <input id="s-betrag" class="feld pr-10 text-2xl font-semibold" inputmode="decimal" placeholder="0,00" bind:value={betrag} />
        <span class="absolute right-4 top-1/2 -translate-y-1/2 text-xl text-muted">€</span>
      </div>
    </div>
    <div>
      <label class="label" for="s-datum">Stand vom</label>
      <DatumFeld id="s-datum" max={heute} bind:wert={tag} />
    </div>
    <button class="knopf-primaer w-full" disabled={!(zahl >= 0) || speichert}>Speichern</button>
  </form>
</Sheet>
