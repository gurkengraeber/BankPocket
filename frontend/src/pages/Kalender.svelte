<script lang="ts">
  import { Hourglass } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import Header from '../components/Header.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import Laden from '../components/Laden.svelte';
  import { api } from '../lib/api';
  import { inTagen, tagUeberschrift } from '../lib/format';
  import { gehe } from '../lib/router.svelte';
  import { fehler } from '../lib/store.svelte';

  let daten = $state<any>(null);
  let zeitraum = $state(45);

  async function laden() {
    try {
      daten = await api(`/kalender?tage=${zeitraum}`);
    } catch (e) {
      fehler(e);
    }
  }

  onMount(laden);
</script>

<div class="px-4">
  <Header titel="Kalender" zurueckZu="#/vertraege" />

  {#if !daten}
    <Laden form="liste" />
  {:else}
    <div class="grid grid-cols-2 gap-3">
      <div class="karte p-4">
        <div class="text-[13px] text-muted">Bis Monatsende fällig</div>
        <Amount wert={daten.monat_ausgaben} klasse="mt-1 block text-[22px] font-bold tracking-tight" />
      </div>
      <div class="karte p-4">
        <div class="text-[13px] text-muted">Erwartete Eingänge</div>
        <Amount wert={daten.monat_einnahmen} farbig klasse="mt-1 block text-[22px] font-bold tracking-tight" />
      </div>
    </div>

    {#each daten.tage as t (t.datum)}
      <div class="flex items-baseline justify-between px-1 pb-2 pt-6">
        {#if t.datum === 'ueberfaellig'}
          <h3 class="flex items-center gap-1.5 text-[15px] font-semibold text-warn"><Hourglass size={16} /> Überfällig</h3>
        {:else}
          <h3 class="text-[15px] font-semibold">{tagUeberschrift(t.datum)} <span class="font-normal text-muted">· {inTagen(t.datum)}</span></h3>
          <Amount wert={t.summe} vorzeichen farbig klasse="text-[14px] text-muted" />
        {/if}
      </div>
      <div class="karte overflow-hidden">
        {#each t.eintraege as e, i (`${e.id}-${i}`)}
          <button class="zeile" onclick={() => gehe(`/vertrag/${e.id}`)}>
            <KategorieAvatar kategorie={e.kategorie} groesse={40} />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[16px]">{e.name}</span>
              <span class="block truncate text-[13px] {e.ueberfaellig ? 'text-warn' : 'text-muted'}">
                {e.ueberfaellig ? `seit ${e.tage_ueberfaellig} Tagen offen` : e.kategorie}
              </span>
            </span>
            <Amount wert={e.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
          </button>
        {/each}
      </div>
    {:else}
      <p class="py-16 text-center text-[15px] text-muted">Keine anstehenden Zahlungen – sobald Verträge erkannt sind, erscheinen sie hier.</p>
    {/each}

    {#if zeitraum < 365 && daten.tage.length}
      <button class="knopf-sekundaer mt-6 w-full" onclick={() => { zeitraum = zeitraum < 90 ? 90 : 365; laden(); }}>
        Weiter vorausschauen
      </button>
    {/if}
  {/if}
</div>
