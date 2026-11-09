<script lang="ts">
  import { Briefcase, CalendarClock, ChevronRight, Phone, Plus, ShieldCheck, SlidersHorizontal, Users } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import Header from '../components/Header.svelte';
  import IconKnopf from '../components/IconKnopf.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import Laden from '../components/Laden.svelte';
  import VersicherungSheet from '../components/VersicherungSheet.svelte';
  import VertragNeu from '../components/VertragNeu.svelte';
  import { api } from '../lib/api';
  import { datum, euro, inTagen, TURNUS } from '../lib/format';
  import { TORTENFARBEN } from '../lib/kategorien';
  import { fehler } from '../lib/store.svelte';
  import { kontaktLink, VERSICHERT, VERWALTUNG, VERWALTUNG_KURZ } from '../lib/versicherung';

  let daten = $state<any>(null);
  let neuOffen = $state(false);
  let artNeu = $state('');
  let detail = $state<any>(null);
  let detailOffen = $state(false);
  let filter = $state('alle'); // nach Verwaltung: alle | direkt | makler | … | offen

  async function laden() {
    try {
      daten = await api('/versicherungen');
    } catch (e) {
      fehler(e);
    }
  }

  const farbe = (i: number) => TORTENFARBEN[i % TORTENFARBEN.length];
  const alle = $derived((daten?.vertraege ?? []).map((c: any, i: number) => ({ ...c, farbe: farbe(i) })));
  // Wo liegen die Verträge? Zählt je Verwaltungsweg – zugleich die Filterknöpfe
  const wege = $derived.by(() => {
    const m = new Map<string, { anzahl: number; monatlich: number }>();
    for (const c of alle) {
      const k = c.verwaltet_ueber || 'offen';
      const e = m.get(k) ?? { anzahl: 0, monatlich: 0 };
      m.set(k, { anzahl: e.anzahl + 1, monatlich: e.monatlich + Number(c.monatlich) });
    }
    return [...m.entries()].map(([weg, w]) => ({ weg, ...w })).sort((a, b) => b.monatlich - a.monatlich);
  });
  const sichtbar = $derived(alle.filter((c: any) => filter === 'alle' || (c.verwaltet_ueber || 'offen') === filter));
  const verwaltung = (c: any) => (c.verwaltet_ueber ? [VERWALTUNG_KURZ[c.verwaltet_ueber], c.verwaltet_name].filter(Boolean).join(' · ') : '');

  function oeffnen(c: any) {
    detail = c;
    detailOffen = true;
  }
  onMount(laden);
</script>

<div class="px-4">
  <Header titel="Versicherungen">
    {#snippet aktionen()}
      <IconKnopf label="Versicherung hinzufügen" onclick={() => { artNeu = ''; neuOffen = true; }}><Plus size={24} /></IconKnopf>
    {/snippet}
  </Header>

  {#if !daten}
    <Laden />
  {:else}
    <section class="karte p-5">
      <div class="text-[15px] font-semibold text-muted">{alle.length} {alle.length === 1 ? 'Versicherung' : 'Versicherungen'}</div>
      <div class="mt-2 flex flex-wrap items-baseline gap-x-2">
        <Amount wert={daten.monatlich} klasse="text-[34px] font-bold tracking-tight" />
        <span class="text-[15px] text-muted">pro Monat · <Amount wert={daten.jaehrlich} kurz /> im Jahr</span>
      </div>
      {#if alle.length > 1}
        <!-- Wer kostet wie viel: ein Balken, je Vertrag ein Stück in seiner Farbe -->
        <div class="mt-4 flex h-3 gap-0.5 overflow-hidden rounded-full">
          {#each alle as c (c.id)}
            <a href="#/vertrag/{c.id}" class="h-full min-w-1" style="width: {c.kostenanteil * 100}%; background: {c.farbe}" aria-label="{c.name}: {euro(c.monatlich)} im Monat"></a>
          {/each}
        </div>
      {/if}
      {#if daten.naechste_kuendigung}
        {@const k = daten.naechste_kuendigung}
        <a href="#/vertrag/{k.id}" class="mt-4 flex items-center gap-2.5 rounded-2xl px-3.5 py-2.5 text-[14px] {k.tage <= 30 ? 'bg-warn-soft text-warn' : 'bg-card-hi'}">
          <CalendarClock size={18} class="shrink-0" />
          <span class="min-w-0 flex-1">Nächster Kündigungstermin: <b class="font-semibold">{datum(k.kuendigen_bis)}</b> <span class="opacity-80">({inTagen(k.kuendigen_bis)}) · {k.name}</span></span>
          <ChevronRight size={16} class="shrink-0" />
        </a>
      {/if}
    </section>

    {#if wege.length > 1 || (wege.length === 1 && wege[0].weg !== 'offen')}
      <div class="-mx-4 mt-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
        <button class="shrink-0 rounded-full px-3.5 py-2 text-[14px] font-semibold {filter === 'alle' ? 'bg-accent text-white' : 'bg-card text-muted'}" onclick={() => (filter = 'alle')}>Alle</button>
        {#each wege as w (w.weg)}
          <button class="shrink-0 rounded-full px-3.5 py-2 text-[14px] font-semibold {filter === w.weg ? 'bg-accent text-white' : 'bg-card text-muted'}" onclick={() => (filter = filter === w.weg ? 'alle' : w.weg)}>
            {w.weg === 'offen' ? 'Ohne Angabe' : VERWALTUNG_KURZ[w.weg]} · {w.anzahl}
          </button>
        {/each}
      </div>
    {/if}

    <div class="mt-4 space-y-2.5 lg:grid lg:grid-cols-2 lg:gap-3 lg:space-y-0">
      {#each sichtbar as c (c.id)}
        <article class="karte overflow-hidden">
          <a class="flex items-center gap-3 px-4 pb-1.5 pt-3 active:bg-card-hi" href="#/vertrag/{c.id}">
            <span class="relative shrink-0">
              <KategorieAvatar kategorie={c.kategorie} logo={c.logo} groesse={40} />
              <span class="absolute -right-1 -top-1 size-3.5 rounded-full border-2 border-[var(--color-card)]" style="background: {c.farbe}"></span>
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[16px] font-semibold">{c.arten.length ? c.arten.join(' + ') : c.name}</span>
              <span class="block truncate text-[13px] text-muted">
                {c.arten.length ? c.name : 'Art noch offen'}{#if c.turnus !== 'monatlich'} · {TURNUS[c.turnus].toLowerCase()} {euro(Math.abs(Number(c.mein_betrag)), { kurz: true })}{/if}{#if c.anteil_prozent < 100} · {c.anteil_prozent} %{/if}
              </span>
            </span>
            <span class="shrink-0 text-right">
              <Amount wert={c.monatlich} klasse="block text-[16px] font-semibold" />
              <span class="block text-[11px] text-muted">im Monat</span>
            </span>
          </a>
          <!-- alles Weitere als kleine Marken in einer Zeile; antippen öffnet die Details -->
          <div class="flex flex-wrap gap-1.5 px-4 pb-3 pt-1 pl-[68px] text-[13px] [&_.pill]:px-2.5 [&_.pill]:py-1 [&_.pill]:text-[13px]">
            {#if !c.art_eingetragen}
              <button class="pill border border-dashed border-accent text-accent" onclick={() => oeffnen(c)}><Plus size={13} />{c.arten[0] ? `${c.arten[0]}?` : 'Art wählen'}</button>
            {/if}
            <button class="pill {verwaltung(c) ? 'bg-card-hi' : 'border border-dashed border-accent text-accent'}" onclick={() => oeffnen(c)}>
              <Briefcase size={13} />{verwaltung(c) || 'Verwaltet über …'}
            </button>
            {#if c.gekuendigt_zum}
              <a class="pill bg-card-hi text-muted" href="#/vertrag/{c.id}"><CalendarClock size={13} />gekündigt zum {datum(c.gekuendigt_zum)}</a>
            {:else if c.kuendigung?.kuendigen_bis && !c.kuendigung.verpasst}
              <a class="pill {c.kuendigung.tage <= 30 ? 'bg-warn-soft text-warn' : 'bg-card-hi'}" href="#/vertrag/{c.id}"><CalendarClock size={13} />kündbar bis {datum(c.kuendigung.kuendigen_bis)}</a>
            {:else if c.kuendigung?.jederzeit}
              <a class="pill bg-card-hi" href="#/vertrag/{c.id}"><CalendarClock size={13} />jederzeit kündbar</a>
            {/if}
            {#if c.versichert}<button class="pill bg-card-hi" onclick={() => oeffnen(c)}><Users size={13} />{VERSICHERT[c.versichert]}</button>{/if}
            {#if c.selbstbeteiligung !== null}
              <button class="pill bg-card-hi" onclick={() => oeffnen(c)}><ShieldCheck size={13} />{Number(c.selbstbeteiligung) ? `SB ${euro(c.selbstbeteiligung, { kurz: true })}` : 'ohne SB'}</button>
            {/if}
            {#if kontaktLink(c.kontakt)}
              <a class="pill-accent" href={kontaktLink(c.kontakt)} target="_blank" rel="noreferrer"><Phone size={13} />Schaden melden</a>
            {/if}
            <button class="pill bg-card-hi text-muted" onclick={() => oeffnen(c)} aria-label="Details zu {c.name} bearbeiten"><SlidersHorizontal size={13} /></button>
          </div>
        </article>
      {:else}
        <div class="karte p-6 text-center text-[15px] text-muted">
          {alle.length ? 'Keine Versicherung mit dieser Verwaltung.' : 'Noch keine Versicherung erfasst. Bestätige erkannte Verträge mit der Kategorie „Versicherung“ oder lege eine von Hand an.'}
        </div>
      {/each}
    </div>

    {#if wege.length && wege.some((w) => w.weg !== 'offen')}
      <h2 class="abschnitt">Wo liegen deine Verträge?</h2>
      <div class="karte divide-y divide-line overflow-hidden">
        {#each wege as w (w.weg)}
          <button class="flex w-full items-center gap-3 px-4 py-3 text-left text-[15px] active:bg-card-hi" onclick={() => { filter = w.weg; window.scrollTo({ top: 0, behavior: 'smooth' }); }}>
            <span class="min-w-0 flex-1">{w.weg === 'offen' ? 'Ohne Angabe' : VERWALTUNG[w.weg]}<span class="text-muted"> · {w.anzahl} {w.anzahl === 1 ? 'Vertrag' : 'Verträge'}</span></span>
            <Amount wert={w.monatlich} klasse="shrink-0" /><span class="text-[13px] text-muted">/ Monat</span>
            <ChevronRight size={16} class="shrink-0 text-faint" />
          </button>
        {/each}
      </div>
    {/if}

    {#if daten.nicht_erfasst.length}
      <h2 class="abschnitt">Nicht erfasst</h2>
      <div class="karte p-4">
        <div class="flex flex-wrap gap-2">
          {#each daten.nicht_erfasst as a (a)}
            <button class="pill bg-card-hi text-muted active:bg-accent-soft active:text-accent" onclick={() => { artNeu = a; neuOffen = true; }}><Plus size={14} />{a}</button>
          {/each}
        </div>
        <p class="mt-3 text-[13px] leading-relaxed text-muted">
          Antippen, um eine davon einzutragen. Übliche Versicherungen, die BankPocket in deinen Verträgen nicht findet –
          etwa weil sie über den Arbeitgeber laufen, jährlich von einem anderen Konto abgehen oder die Art noch nicht
          eingetragen ist. Das ist eine Merkliste, keine Empfehlung.
        </p>
      </div>
    {/if}
  {/if}
</div>

<VertragNeu bind:offen={neuOffen} ongespeichert={laden} kategorieVorgabe="Versicherung" artVorgabe={artNeu} />
<VersicherungSheet bind:offen={detailOffen} vertrag={detail} arten={daten?.arten ?? []} ongespeichert={laden} />
