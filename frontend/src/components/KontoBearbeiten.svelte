<script lang="ts">
  import { api } from '../lib/api';
  import { gehe } from '../lib/router.svelte';
  import { fehler, toast } from '../lib/store.svelte';
  import Sheet from './Sheet.svelte';

  let { offen = $bindable(false), konto, ongespeichert }: {
    offen: boolean;
    konto: { id: number; name: string; gruppe?: string; connection_id?: number | null; aktiv?: boolean } | null;
    ongespeichert?: () => void;
  } = $props();

  let name = $state('');
  let gruppe = $state('');
  const GRUPPEN = ['Tägliche Konten', 'Sparkonten', 'Crypto', 'Virtuell'];
  let speichert = $state(false);

  // Beim Öffnen den bisherigen Namen vorbelegen
  $effect(() => {
    if (offen) {
      name = konto?.name ?? '';
      gruppe = konto?.gruppe ?? '';
    }
  });

  async function speichern(e: SubmitEvent) {
    e.preventDefault();
    if (!konto || !name.trim()) return;
    speichert = true;
    try {
      await api(`/accounts/${konto.id}`, { method: 'PATCH', body: { name: name.trim(), ...(gruppe ? { gruppe } : {}) } });
      toast('Gespeichert');
      offen = false;
      ongespeichert?.();
    } catch (err) {
      fehler(err);
    } finally {
      speichert = false;
    }
  }

  async function ausblenden() {
    if (!konto) return;
    const aktiv = konto.aktiv === false;
    try {
      await api(`/accounts/${konto.id}`, { method: 'PATCH', body: { aktiv } });
      toast(aktiv ? 'Konto wieder eingeblendet' : 'Konto ausgeblendet');
      offen = false;
      if (aktiv) ongespeichert?.();
      else gehe('/');
    } catch (err) {
      fehler(err);
    }
  }

  async function loeschen() {
    if (!konto) return;
    if (!confirm(`„${konto.name}“ mit allen Buchungen und Ständen löschen? Das lässt sich nicht rückgängig machen.`)) return;
    try {
      await api(`/accounts/${konto.id}`, { method: 'DELETE' });
      toast('Konto gelöscht');
      offen = false;
      gehe('/');
    } catch (err) {
      fehler(err);
    }
  }
</script>

<Sheet bind:offen titel="Konto bearbeiten">
  <form onsubmit={speichern} class="space-y-4">
    <div><label class="label" for="k-name">Name</label><input id="k-name" class="feld" placeholder="z. B. Norwegian Kreditkarte" bind:value={name} /></div>
    <div>
      <label class="label" for="k-gruppe">Gruppe in der Übersicht</label>
      <select id="k-gruppe" class="feld appearance-none" bind:value={gruppe}>
        {#each GRUPPEN as g (g)}<option value={g}>{g}</option>{/each}
      </select>
    </div>
    <button class="knopf-primaer w-full" disabled={!name.trim() || speichert}>Speichern</button>
  </form>
  <div class="mt-6 border-t border-line pt-4">
    <button class="knopf-sekundaer w-full" onclick={ausblenden}>
      {konto?.aktiv === false ? 'Konto wieder einblenden' : 'Konto ausblenden'}
    </button>
    <p class="mb-5 mt-2 text-center text-[12px] leading-relaxed text-faint">
      {konto?.aktiv === false
        ? 'Das Konto erscheint dann wieder in der Übersicht und zählt zur Summe.'
        : 'Ausgeblendete Konten stehen nicht in der Übersicht und zählen nicht zur Summe. Buchungen und Abrufe bleiben. Zurückholen über „ausgeblendete Konten anzeigen“ unten in der Übersicht.'}
    </p>
    {#if konto?.connection_id}
      <p class="text-[13px] leading-relaxed text-muted">
        Dieses Konto gehört zu einer Bankverbindung. Zum Löschen zuerst die
        <a class="font-medium text-accent" href="#/verbindung/{konto.connection_id}" onclick={() => (offen = false)}>Verbindung</a> entfernen.
      </p>
    {:else}
      <button class="knopf-gefahr w-full" onclick={loeschen}>Konto löschen</button>
      <p class="mt-2 text-center text-[12px] text-faint">Löscht auch alle Buchungen, Stände und Positionen dieses Kontos.</p>
    {/if}
  </div>
</Sheet>
