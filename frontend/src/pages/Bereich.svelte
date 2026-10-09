<script lang="ts">
  import { ChevronRight, Pencil } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import Auswahl from '../components/Auswahl.svelte';
  import BereichSheet from '../components/BereichSheet.svelte';
  import BuchungDetail from '../components/BuchungDetail.svelte';
  import Header from '../components/Header.svelte';
  import IconKnopf from '../components/IconKnopf.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import Laden from '../components/Laden.svelte';
  import Sheet from '../components/Sheet.svelte';
  import { api } from '../lib/api';
  import { datum, datumKurz, euro, monatName } from '../lib/format';
  import { gehe } from '../lib/router.svelte';
  import { fehler, merker, toast } from '../lib/store.svelte';

  let { id }: { id: number } = $props();

  let b = $state<any>(null);
  let aendernOffen = $state(false);
  let monat = $state<string | null>(null);
  let belegeOffen = $state(false);
  let belege = $state<any[] | null>(null);
  let filter = $state<any>(null); // nur ein Posten des Monats
  let detailId = $state<number | null>(null);
  let detailOffen = $state(false);

  const max = $derived(Math.max(1, ...(b?.monate ?? []).map((m: any) => Math.abs(Number(m.summe)))));

  // Schnitt über die letzten 3, 6 oder 12 vollen Monate – die Wahl gilt für alle Bereiche
  let fenster = $state(Number(merker.lesen('bp_bereichfenster') ?? 6));
  function fensterWaehlen(n: number) {
    fenster = n;
    merker.schreiben('bp_bereichfenster', String(n));
    laden();
  }
  const imFenster = (m: string) => !!b?.von && m >= b.von && m !== b.monate[b.monate.length - 1].monat;

  async function laden() {
    try {
      b = await api(`/bereiche/${id}?fenster=${fenster}`);
    } catch (e) {
      fehler(e);
    }
  }

  async function belegeLaden() {
    try {
      const p = new URLSearchParams(filter ? { kategorie: filter.name, fenster: String(fenster) } : { monat: monat! });
      belege = (await api(`/bereiche/${id}/buchungen?${p}`)).buchungen;
    } catch (e) {
      fehler(e);
    }
  }

  function monatZeigen(m: string) {
    monat = m;
    filter = null;
    belege = null;
    belegeOffen = true;
    belegeLaden();
  }

  // Posten „Kategorie“: die einzelnen Buchungen der letzten zwölf Monate dahinter
  function postenZeigen(p: any) {
    filter = p;
    monat = null;
    belege = null;
    belegeOffen = true;
    belegeLaden();
  }

  async function loeschen() {
    if (!confirm(`Bereich „${b.name}“ löschen? Buchungen und Verträge bleiben unverändert.`)) return;
    await api(`/bereiche/${id}`, { method: 'DELETE' }).catch(fehler);
    toast('Bereich gelöscht');
    gehe('/analysen');
  }

  onMount(laden);
</script>

<div class="px-4">
  <Header titel={b ? `${b.emoji} ${b.name}` : 'Bereich'} zurueckZu="#/analysen">
    {#snippet aktionen()}
      <IconKnopf label="Bereich ändern" onclick={() => (aendernOffen = true)}><Pencil size={20} /></IconKnopf>
    {/snippet}
  </Header>

  {#if !b}
    <Laden />
  {:else}
    <section class="karte p-5">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="text-[15px] font-semibold text-muted">Kostet dich im Schnitt</span>
        <Auswahl optionen={[[3, '3 Monate'], [6, '6 Monate'], [12, '12 Monate']]} bind:wert={fenster} onwahl={fensterWaehlen} />
      </div>
      <div class="mt-2 flex flex-wrap items-baseline gap-x-2">
        <Amount wert={b.schnitt} klasse="text-[34px] font-bold tracking-tight" />
        <span class="text-[15px] text-muted">pro Monat · <Amount wert={b.jahr} kurz /> im Jahr</span>
      </div>
      <p class="mt-1 text-[13px] text-muted">
        Schnitt der letzten {b.zeitraum} {b.zeitraum === 1 ? 'vollen Monats' : 'vollen Monate'}{#if b.zeitraum < b.fenster} (mehr Daten gibt es noch nicht){/if}{#if Number(b.fix_monatlich) > 0} · davon <Amount wert={b.fix_monatlich} /> feste Verträge{/if}
      </p>

      <div class="mt-5 flex h-32 items-end gap-1">
        {#each b.monate as m (m.monat)}
          <button class="flex h-full flex-1 items-end justify-center rounded-lg active:bg-card-hi {imFenster(m.monat) ? '' : 'opacity-40'}" onclick={() => monatZeigen(m.monat)} aria-label="{monatName(m.monat)}: {euro(m.summe)}">
            <span class="w-2.5 rounded-full {Number(m.summe) < 0 ? 'bg-pos' : 'bg-accent'}" style="height: {Math.max(3, (Math.abs(Number(m.summe)) / max) * 100)}%"></span>
          </button>
        {/each}
      </div>
      <div class="mt-1 flex gap-1">
        {#each b.monate as m (m.monat)}<span class="flex-1 text-center text-[10px] font-medium text-muted">{monatName(m.monat, true).slice(0, 3)}</span>{/each}
      </div>
      <p class="mt-2 text-[12px] text-faint">Einen Monat antippen zeigt die Buchungen. Blasse Monate zählen nicht in den Schnitt – der laufende nie.</p>
    </section>

    <h2 class="abschnitt">Woraus es sich zusammensetzt</h2>
    <div class="karte overflow-hidden">
      {#each b.posten as p (p.art + p.name)}
        <svelte:element this={p.art === 'vertrag' ? 'a' : 'button'} class="zeile" href={p.art === 'vertrag' ? `#/vertrag/${p.id}` : undefined} onclick={p.art === 'vertrag' ? undefined : () => postenZeigen(p)} role={p.art === 'vertrag' ? undefined : 'button'}>
          <KategorieAvatar kategorie={p.kategorie} groesse={38} />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[16px]">{p.name}</span>
            <span class="block truncate text-[13px] text-muted">{p.art === 'vertrag' ? `Vertrag · ${p.kategorie}` : 'Kategorie'} · {p.anzahl} {p.anzahl === 1 ? 'Buchung' : 'Buchungen'}</span>
          </span>
          <span class="shrink-0 text-right">
            <Amount wert={p.schnitt} klasse="block text-[16px] font-medium" />
            <span class="block text-[11px] text-muted">im Monat</span>
          </span>
          <ChevronRight size={18} class="shrink-0 text-faint" />
        </svelte:element>
      {:else}
        <div class="p-6 text-center text-[15px] text-muted">Noch keine Buchungen in diesem Bereich.</div>
      {/each}
    </div>
    <p class="mt-3 px-1 text-[13px] leading-relaxed text-muted">
      Bei geteilten Verträgen zählt dein Anteil. Jährliche und vierteljährliche Zahlungen sind auf den Monat umgelegt.
    </p>

    <button class="knopf-sekundaer mt-6 w-full" onclick={() => (aendernOffen = true)}><Pencil size={17} /> Kategorien und Verträge ändern</button>
    <button class="knopf-gefahr mt-3 w-full" onclick={loeschen}>Bereich löschen</button>
  {/if}
</div>

<BereichSheet bind:offen={aendernOffen} bereich={b} ongespeichert={laden} />

<Sheet bind:offen={belegeOffen} titel={filter ? `${filter.name} · letzte ${b?.zeitraum} Monate` : monat ? `${b?.name} · ${monatName(monat)}` : ''}>
  {#if !belege}
    <Laden form="liste" />
  {:else if !belege.length}
    <p class="py-8 text-center text-[15px] text-muted">Keine Buchungen.</p>
  {:else}
    <div class="karte overflow-hidden">
      {#each belege as x (x.id)}
        <button class="zeile" onclick={() => { detailId = x.id; detailOffen = true; }}>
          <KategorieAvatar kategorie={x.kategorie} logo={x.logo} groesse={40} rund />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[16px]">{x.gegenpartei || x.verwendungszweck || x.buchungstext || 'Buchung'}</span>
            <span class="block truncate text-[13px] text-muted">{filter ? datum(x.datum) : datumKurz(x.datum)} · {x.mein_betrag ? `dein Anteil ${euro(Math.abs(Number(x.mein_betrag)))}` : x.kategorie}</span>
          </span>
          <Amount wert={x.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
        </button>
      {/each}
    </div>
  {/if}
</Sheet>
<BuchungDetail bind:offen={detailOffen} id={detailId} ongeaendert={() => { laden(); belegeLaden(); }} />
