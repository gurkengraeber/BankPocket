<script lang="ts">
  import { api } from '../lib/api';
  import { gehe } from '../lib/router.svelte';
  import { fehler, toast } from '../lib/store.svelte';
  import Sheet from './Sheet.svelte';

  let { offen = $bindable(false), konto, ongespeichert }: {
    offen: boolean;
    konto: { id: number; name: string; gruppe?: string; connection_id?: number | null; aktiv?: boolean; typ?: string } | null;
    ongespeichert?: () => void;
  } = $props();

  let name = $state('');
  let gruppe = $state('');
  const GRUPPEN = ['Tägliche Konten', 'Sparkonten', 'Crypto', 'Virtuell'];
  let speichert = $state(false);
  // Zusammenführen: andere Konten als Ziel (keine Depots)
  let ziele = $state<any[]>([]);
  let ziel = $state<number | ''>('');
  let fuehrtZusammen = $state(false);

  // Beim Öffnen den bisherigen Namen vorbelegen
  $effect(() => {
    if (offen) {
      name = konto?.name ?? '';
      gruppe = konto?.gruppe ?? '';
      ziel = '';
      if (konto && !konto.connection_id && konto.typ !== 'depot')
        api('/accounts')
          .then((d) => (ziele = d.gruppen.flatMap((g: any) => g.konten).filter((k: any) => k.id !== konto!.id && k.typ !== 'depot')))
          .catch(fehler);
      else ziele = [];
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

  async function zusammenfuehren() {
    if (!konto || ziel === '') return;
    const zielKonto = ziele.find((k) => k.id === ziel);
    if (!confirm(`Alle Buchungen von „${konto.name}“ nach „${zielKonto?.name}“ übernehmen? „${konto.name}“ wird danach aufgelöst. Buchungen, die es in beiden gibt (gleiches Datum, gleicher Betrag), bleiben einmal stehen – mit deinen Kategorien und Verträgen.`)) return;
    fuehrtZusammen = true;
    try {
      const r = await api(`/accounts/${konto.id}/zusammenfuehren`, { body: { ziel_id: ziel } });
      toast(`${r.uebernommen} Buchungen übernommen${r.doppelt ? `, ${r.doppelt} davon gab es schon` : ''}`);
      offen = false;
      gehe(`/konto/${r.ziel_id}`);
    } catch (err) {
      fehler(err);
    } finally {
      fuehrtZusammen = false;
    }
  }

  async function loeschen() {
    if (!konto) return;
    let folgen = '';
    try {
      const f = await api(`/accounts/${konto.id}/folgen`);
      if (f.buchungen) folgen = ` Damit verschwinden ${f.buchungen} Buchungen`;
      if (f.vertraege)
        folgen += ` – und ${f.vertraege} ${f.vertraege === 1 ? 'Vertrag verliert' : 'Verträge verlieren'} alle Zahlungen (${f.beispiele.join(', ')}${f.vertraege > f.beispiele.length ? ' …' : ''})`;
      if (folgen) folgen += '. Zum Aufräumen genügt „Konto ausblenden“; ein altes Konto lässt sich auch in ein anderes übernehmen.';
    } catch {
      /* die Rückfrage kommt auch ohne die Zahlen */
    }
    if (!confirm(`„${konto.name}“ mit allen Buchungen und Ständen löschen? Das lässt sich nicht rückgängig machen.${folgen}`)) return;
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
      {#if ziele.length}
        <label class="label" for="k-ziel">In ein anderes Konto übernehmen</label>
        <div class="flex gap-2">
          <select id="k-ziel" class="feld min-w-0 flex-1 appearance-none" bind:value={ziel}>
            <option value="">Konto wählen …</option>
            {#each ziele as k (k.id)}<option value={k.id}>{k.name}</option>{/each}
          </select>
          <button class="knopf-sekundaer shrink-0 !px-4" disabled={ziel === '' || fuehrtZusammen} onclick={zusammenfuehren}>Übernehmen</button>
        </div>
        <p class="mb-5 mt-2 text-[12px] leading-relaxed text-faint">
          Für ein früheres CSV- oder Handkonto, das es inzwischen als Bankverbindung gibt: Die Buchungen wandern mit
          Kategorien und Verträgen ins gewählte Konto, doppelte bleiben einmal stehen.
        </p>
      {/if}
      <button class="knopf-gefahr w-full" onclick={loeschen}>Konto löschen</button>
      <p class="mt-2 text-center text-[12px] text-faint">Löscht auch alle Buchungen, Stände und Positionen dieses Kontos.</p>
    {/if}
  </div>
</Sheet>
