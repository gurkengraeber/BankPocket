<script lang="ts">
  import { api } from '../lib/api';
  import { fehler, toast } from '../lib/store.svelte';
  import ArtenWahl from './ArtenWahl.svelte';
  import Auswahl from './Auswahl.svelte';
  import Sheet from './Sheet.svelte';
  import { VERSICHERT, VERWALTUNG, VERWALTUNG_NAMEN } from '../lib/versicherung';

  // Wo liegt der Vertrag, wer ist versichert, was gilt im Schadensfall – alles per Knopf
  let { offen = $bindable(false), vertrag, arten = [], ongespeichert }: { offen: boolean; vertrag: any; arten?: string[]; ongespeichert?: () => void } = $props();

  let f = $state({ art: [] as string[], verwaltet_ueber: '', verwaltet_name: '', versichert: '', sb: -1 as number, kontakt: '' });
  $effect(() => {
    if (offen && vertrag) {
      f = { art: (vertrag.art || '').split(',').map((x: string) => x.trim()).filter(Boolean), verwaltet_ueber: vertrag.verwaltet_ueber, verwaltet_name: vertrag.verwaltet_name, versichert: vertrag.versichert,
        sb: vertrag.selbstbeteiligung === null ? -1 : Number(vertrag.selbstbeteiligung), kontakt: vertrag.kontakt };
    }
  });
  const namen = $derived(VERWALTUNG_NAMEN[f.verwaltet_ueber] ?? []);

  async function speichern(e: SubmitEvent) {
    e.preventDefault();
    try {
      await api(`/contracts/${vertrag.id}`, { method: 'PATCH', body: {
        ...(arten.length ? { art: f.art.join(', ') } : {}),
        verwaltet_ueber: f.verwaltet_ueber, verwaltet_name: f.verwaltet_ueber && f.verwaltet_ueber !== 'direkt' ? f.verwaltet_name : '',
        versichert: f.versichert, selbstbeteiligung: f.sb < 0 ? null : f.sb, kontakt: f.kontakt } });
      toast('Gespeichert');
      offen = false;
      ongespeichert?.();
    } catch (err) {
      fehler(err);
    }
  }
</script>

<Sheet bind:offen titel={vertrag?.name ?? 'Versicherung'}>
  <form class="space-y-5" onsubmit={speichern}>
    {#if arten.length}
      <div>
        <div class="label">Was ist versichert?</div>
        <ArtenWahl {arten} gewaehlt={f.art} vorschlag={vertrag?.art ? '' : (vertrag?.art_vorschlag ?? '')} onaendern={(liste) => (f.art = liste)} />
        <p class="mt-1.5 text-[13px] text-muted">Mehrere wählen, wenn der Vertrag mehrere Versicherungen bündelt.</p>
      </div>
    {/if}
    <div>
      <div class="label">Abgeschlossen und verwaltet über</div>
      <Auswahl optionen={[['', 'Keine Angabe'], ...Object.entries(VERWALTUNG)]} bind:wert={f.verwaltet_ueber} onwahl={() => (f.verwaltet_name = '')} />
      {#if f.verwaltet_ueber && f.verwaltet_ueber !== 'direkt'}
        <div class="mt-3">
          <div class="label">{f.verwaltet_ueber === 'makler' ? 'Wer ist dein Makler?' : 'Welche?'}</div>
          {#if namen.length}
            <Auswahl optionen={namen.map((n) => [n, n])} bind:wert={f.verwaltet_name} andere platzhalter="Name" />
          {:else}
            <input class="feld" placeholder={f.verwaltet_ueber === 'makler' ? 'Name oder Büro' : 'Name'} bind:value={f.verwaltet_name} />
          {/if}
        </div>
      {/if}
    </div>
    <div>
      <div class="label">Wer ist versichert?</div>
      <Auswahl optionen={[['', 'Keine Angabe'], ...Object.entries(VERSICHERT)]} bind:wert={f.versichert} />
    </div>
    <div>
      <div class="label">Selbstbeteiligung</div>
      <Auswahl optionen={[[-1, 'Keine Angabe'], [0, 'Keine'], [150, '150 €'], [250, '250 €'], [300, '300 €'], [500, '500 €'], [1000, '1.000 €']]} bind:wert={f.sb} andere einheit="€" platzhalter="Betrag" />
    </div>
    <div>
      <label class="label" for="vs-kontakt">Schaden melden</label>
      <input id="vs-kontakt" class="feld" placeholder="Telefonnummer oder Internetadresse" autocapitalize="off" bind:value={f.kontakt} />
      <p class="mt-1.5 text-[13px] text-muted">Steht dann als Knopf in der Übersicht – im Schadensfall ein Tipp.</p>
    </div>
    <button class="knopf-primaer w-full">Speichern</button>
  </form>
</Sheet>
