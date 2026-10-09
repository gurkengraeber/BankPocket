<script lang="ts">
  import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Lock, TrendingDown, TrendingUp } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import BereichSheet from '../components/BereichSheet.svelte';
  import BuchungDetail from '../components/BuchungDetail.svelte';
  import Header from '../components/Header.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import KategorieTorte from '../components/KategorieTorte.svelte';
  import Laden from '../components/Laden.svelte';
  import MonatsBalken from '../components/MonatsBalken.svelte';
  import Sheet from '../components/Sheet.svelte';
  import VermoegenChart from '../components/VermoegenChart.svelte';
  import { api } from '../lib/api';
  import { datum, datumKurz, euro, monatName } from '../lib/format';
  import { emoji, TORTENFARBEN } from '../lib/kategorien';
  import { gehe } from '../lib/router.svelte';
  import { fehler, merker } from '../lib/store.svelte';

  const ZEITRAEUME: [number, string][] = [[90, '3 M'], [180, '6 M'], [365, '1 J'], [730, '2 J']];
  let zeitraum = $state(Number(merker.lesen('bp_zeitraum') ?? 365));
  let vermoegen = $state<any>(null);
  let analyse = $state<any>(null);
  let unklar = $state(0);

  const jetzt = new Date();
  const dieserMonat = `${jetzt.getFullYear()}-${String(jetzt.getMonth() + 1).padStart(2, '0')}`;

  async function vermoegenLaden() {
    try {
      vermoegen = await api(`/analysen/vermoegen?tage=${zeitraum}`);
    } catch (e) {
      fehler(e);
    }
  }

  // Die sechs Balken bleiben beim Wechseln stehen; das Fenster rückt nur, wenn der gewählte Monat außerhalb läge
  let fensterEnde = dieserMonat;
  const plusMonate = (monat: string, n: number) => {
    const [j, m] = monat.split('-').map(Number);
    const d = new Date(j, m - 1 + n, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  };

  // Monat oder ganzes Jahr: dieselbe Auswertung, im Jahr mit zwölf Balken, Vorjahresvergleich und Steuerliste
  let modus = $state<'monat' | 'jahr'>('monat');
  const zeitraumText = $derived(!analyse ? '' : analyse.monat ? monatName(analyse.monat) : String(analyse.jahr));

  async function jahrLaden(j: number) {
    try {
      analyse = await api(`/analysen/jahr?jahr=${j}`);
      modus = 'jahr';
    } catch (e) {
      fehler(e);
    }
  }

  function modusWaehlen(m: 'monat' | 'jahr') {
    if (m === modus || !analyse) return;
    if (m === 'jahr') jahrLaden(Number(analyse.monat.slice(0, 4)));
    else monatLaden(analyse.jahr === jetzt.getFullYear() ? dieserMonat : `${analyse.jahr}-12`);
  }

  const veraenderung = (neu: number | string, vorher: number | string) => {
    const v = Number(vorher);
    if (!v) return null;
    const p = Math.round(((Number(neu) - v) / Math.abs(v)) * 100);
    return `${p > 0 ? '+' : ''}${p} %`;
  };

  async function monatLaden(m: string = dieserMonat) {
    modus = 'monat';
    if (m > fensterEnde) fensterEnde = m;
    else if (m < plusMonate(fensterEnde, -5)) fensterEnde = plusMonate(m, 5);
    try {
      analyse = await api(`/analysen/monat?monat=${m}&verlauf_bis=${fensterEnde}`);
    } catch (e) {
      fehler(e);
    }
  }

  // Klick auf eine Zahl der Monatsanalyse zeigt die Buchungen dahinter
  const ART_TITEL: Record<string, string> = { einnahme: 'Einnahmen', ausgabe: 'Ausgaben', gespart: 'Gespart' };
  let belegeOffen = $state(false);
  let belegeTitel = $state('');
  let belege = $state<any[] | null>(null);
  let belegeFilter = { art: 'ausgabe', kategorie: null as string | null, tag: null as string | null, empfaenger: null as string | null };
  let detailId = $state<number | null>(null);
  let detailOffen = $state(false);

  async function belegeLaden() {
    const p = new URLSearchParams({ art: belegeFilter.art });
    if (belegeMonat) p.set('monat', belegeMonat);
    else if (analyse.monat) p.set('monat', analyse.monat);
    else p.set('jahr', String(analyse.jahr));
    if (belegeFilter.empfaenger) p.set('empfaenger', belegeFilter.empfaenger);
    if (belegeFilter.kategorie) p.set('kategorie', belegeFilter.kategorie);
    if (belegeFilter.tag) p.set('tag', belegeFilter.tag);
    try {
      belege = (await api(`/analysen/buchungen?${p}`)).buchungen;
    } catch (e) {
      fehler(e);
    }
  }

  // Buchungen einer Kategorie in einem bestimmten Monat – unabhängig vom oben gewählten Zeitraum
  let belegeMonat: string | null = null;
  function trendBelege(kategorie: string, monat: string) {
    belegeMonat = monat;
    belegeFilter = { art: 'ausgabe', kategorie, tag: null, empfaenger: null };
    belegeTitel = `${kategorie} · ${monatName(monat)}`;
    belege = null;
    belegeOffen = true;
    belegeLaden();
  }

  function belegeZeigen(art: string, kategorie: string | null = null, tag: string | null = null, empfaenger: string | null = null) {
    belegeMonat = null;
    belegeFilter = { art, kategorie, tag, empfaenger };
    belegeTitel = `${empfaenger ?? (tag ? `#${tag}` : (kategorie ?? ART_TITEL[art]))} · ${zeitraumText}`;
    belege = null;
    belegeOffen = true;
    belegeLaden();
  }

  function schieben(delta: number) {
    if (modus === 'jahr') jahrLaden(analyse.jahr + delta);
    else monatLaden(plusMonate(analyse.monat, delta));
  }

  function zeitraumWaehlen(t: number) {
    zeitraum = t;
    merker.schreiben('bp_zeitraum', String(t));
    vermoegenLaden();
  }

  // Eine Farbe je Kategorie nach Rang – Torte und Balken darunter nutzen dieselbe, Nachbarn unterscheiden sich
  const kategorieFarbe = $derived<Record<string, string>>(
    Object.fromEntries((analyse?.kategorien ?? []).map((k: any, i: number) => [k.kategorie, TORTENFARBEN[i % TORTENFARBEN.length]])),
  );
  // Kleine Stücke (unter 2 %) wären in der Torte nicht zu sehen – sie werden zu „Übrige“ zusammengefasst
  const tortenstuecke = $derived.by(() => {
    const alle = (analyse?.kategorien ?? []).map((k: any) => ({ ...k, farbe: kategorieFarbe[k.kategorie] }));
    const gross = alle.filter((k: any, i: number) => k.anteil >= 0.02 && i < 11);
    const klein = alle.filter((k: any) => !gross.includes(k));
    if (klein.length > 1) {
      gross.push({ kategorie: 'Übrige', farbe: '#8a93a8', anteil: klein.reduce((s: number, k: any) => s + k.anteil, 0),
        summe: klein.reduce((s: number, k: any) => s + Number(k.summe), 0) });
      return gross;
    }
    return alle;
  });

  let tortenWahl = $state<string | null>(null);

  // Die Liste zeigt zuerst nur die größten Kategorien – der Rest klappt auf
  const KATEGORIEN_KURZ = 6;
  let alleKategorien = $state(false);
  const kategorienSichtbar = $derived.by(() => {
    const alle = analyse?.kategorien ?? [];
    return alleKategorien || alle.length <= KATEGORIEN_KURZ + 1 ? alle : alle.slice(0, KATEGORIEN_KURZ);
  });
  const kategorienMehr = $derived((analyse?.kategorien.length ?? 0) - kategorienSichtbar.length);
  const kategorienRest = $derived(
    (analyse?.kategorien ?? []).slice(kategorienSichtbar.length).reduce((s: number, k: any) => s + Number(k.summe), 0),
  );

  // Lebensbereiche: „Was kostet meine Wohnung?“ – Kategorien und Verträge zu einem Thema
  let bereiche = $state<any>(null);
  let bereichNeuOffen = $state(false);
  const bereicheLaden = () => api(`/bereiche?fenster=${Number(merker.lesen('bp_bereichfenster') ?? 6)}`).then((d) => (bereiche = d)).catch(() => (bereiche = { bereiche: [], vorlagen: [] }));
  async function bereichAnlegen(vorlage: any) {
    try {
      gehe(`/bereich/${(await api('/bereiche', { body: vorlage })).id}`);
    } catch (e) {
      fehler(e);
    }
  }

  // Verlauf einer Kategorie über die letzten zwölf Monate
  let trend = $state<any>(null);
  let trendKategorie = $state<string | null>(null);
  let trendMonat = $state<string | null>(null);
  const trendReihe = $derived(trend?.kategorien.find((k: any) => k.kategorie === trendKategorie) ?? trend?.kategorien[0] ?? null);
  const trendMax = $derived(Math.max(1, ...(trendReihe?.werte ?? []).map(Number)));

  // Fragen in normaler Sprache: Die KI übersetzt nur die Frage, gerechnet wird auf dem eigenen Server
  const BEISPIELE = ['Wie viel für Lebensmittel in den letzten 3 Monaten?', 'Wo gebe ich dieses Jahr am meisten aus?', 'Restaurants dieser Monat gegen letzten Monat'];
  let kiBereit = $state<boolean | null>(null);
  let frage = $state('');
  let fragt = $state(false);
  let antwort = $state<any>(null);

  async function fragen(text = frage) {
    if (text.trim().length < 3 || fragt) return;
    frage = text;
    fragt = true;
    try {
      antwort = await api('/ki/frage', { body: { frage: text } });
    } catch (e) {
      fehler(e);
    }
    fragt = false;
  }

  const steigt = $derived(Number(vermoegen?.veraenderung ?? 0) >= 0);

  onMount(() => {
    // Eins nach dem anderen, das Wichtigste zuerst: Gleichzeitig bremsen sich die Auswertungen auf dem Server
    // gegenseitig aus (gemessen: alle vier zusammen 1,1 s, nacheinander 0,4 s – und der Monat steht nach 60 ms).
    (async () => {
      // In den ersten Tagen eines Monats ist der Vormonat aussagekräftiger
      await monatLaden(jetzt.getDate() <= 5 ? plusMonate(dieserMonat, -1) : dieserMonat);
      await vermoegenLaden();
      await bereicheLaden();
      await api('/analysen/kategorien-verlauf').then((d) => (trend = d)).catch(() => (trend = { monate: [], kategorien: [] }));
      api('/unklar').then((d) => (unklar = d.anzahl)).catch(() => {});
      api('/ki').then((d) => (kiBereit = d.schluessel_gesetzt)).catch(() => {});
    })();
  });
</script>

<div class="px-4">
  <Header titel="Analysen" />

  <!-- Am PC zwei Spalten: links der lange Blick (Vermögen, Bereiche, Verlauf, Fragen), rechts der gewählte Monat
       oder das Jahr mit allem, was daran hängt. Am Handy eine Spalte: Vermögen, dann der Zeitraum, dann der Rest. -->
  <div class="flex flex-col lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-8">
    <div class="contents min-w-0 lg:block">
      <div class="order-1">
        <h2 class="abschnitt !pt-1">Vermögen</h2>
        <section class="karte p-5">
          {#if !vermoegen}
            <Laden form="block" />
            <span class="schimmer mt-5 block h-11 rounded-2xl"></span>
          {:else}
            <Amount wert={vermoegen.aktuell} klasse="text-[30px] font-bold tracking-tight" />
            {#if vermoegen.punkte.length > 1}
              <div class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
                <span class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[14px] font-semibold {steigt ? 'bg-accent-soft text-pos' : 'bg-neg-soft text-neg'}">
                  {#if steigt}<TrendingUp size={16} />{:else}<TrendingDown size={16} />{/if}
                  <Amount wert={vermoegen.veraenderung} vorzeichen kurz />
                  {#if vermoegen.veraenderung_prozent !== null}
                    <span class="font-medium opacity-80">({vermoegen.veraenderung_prozent > 0 ? '+' : ''}{(vermoegen.veraenderung_prozent * 100).toLocaleString('de-DE', { maximumFractionDigits: 1 })} %)</span>
                  {/if}
                </span>
                <span class="text-[13px] text-muted">seit {datum(vermoegen.punkte[0].d)}</span>
              </div>
            {:else}
              <div class="text-[13px] text-muted">Gesamtvermögen heute</div>
            {/if}
            <div class="mt-6">
              {#if vermoegen.punkte.length > 1}
                <VermoegenChart punkte={vermoegen.punkte} prognose={vermoegen.prognose} />
              {:else}
                <p class="py-12 text-center text-[15px] text-muted">Noch zu wenig Daten – der Verlauf füllt sich mit jedem Abruf.</p>
              {/if}
            </div>
            <div class="mt-5 grid grid-cols-4 gap-1 rounded-2xl bg-bg p-1">
              {#each ZEITRAEUME as [t, label] (t)}
                <button
                  class="rounded-xl py-2 text-[14px] font-semibold transition-colors {zeitraum === t ? 'bg-card-hi text-text' : 'text-muted'}"
                  onclick={() => zeitraumWaehlen(t)}>{label}</button
                >
              {/each}
            </div>
            {#if vermoegen.prognose.length}
              <p class="mt-3 text-[12px] text-faint">Gestrichelt: Prognose aus der Entwicklung der letzten 90 Tage.</p>
            {/if}
          {/if}
        </section>
      </div>

      <div class="order-3">
        <h2 class="abschnitt">Was kostet …?</h2>
        <div class="-mx-4 flex gap-2.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none] lg:mx-0 lg:px-0">
          {#if !bereiche}
            {#each Array(3) as _, i (i)}
              <div class="karte w-40 shrink-0 space-y-2.5 p-3.5" aria-hidden="true">
                <span class="schimmer block size-7 rounded-lg"></span>
                <span class="schimmer block h-3.5 w-2/3 rounded-full"></span>
                <span class="schimmer block h-5 w-1/2 rounded-full"></span>
                <span class="schimmer block h-2.5 w-3/4 rounded-full"></span>
              </div>
            {/each}
          {:else}
            {#each bereiche.bereiche as b (b.id)}
              <a href="#/bereich/{b.id}" class="karte w-40 shrink-0 p-3.5 active:bg-card-hi">
                <div class="text-[22px]">{b.emoji}</div>
                <div class="mt-1 truncate text-[15px] font-semibold">{b.name}</div>
                <Amount wert={b.schnitt} kurz klasse="block text-[19px] font-bold tracking-tight" />
                <div class="text-[12px] text-muted">im Monat · Ø {b.zeitraum} M</div>
              </a>
            {/each}
            {#each bereiche.vorlagen as v (v.name)}
              <button class="w-40 shrink-0 rounded-[var(--radius-card)] border border-dashed border-accent p-3.5 text-left text-accent active:bg-accent-soft" onclick={() => bereichAnlegen(v)}>
                <div class="text-[22px]">{v.emoji}</div>
                <div class="mt-1 truncate text-[15px] font-semibold">{v.name}</div>
                <div class="mt-1 text-[13px] leading-snug">Antippen: {v.kategorien.slice(0, 3).join(', ')}{v.vertraege.length ? ` + ${v.vertraege.length} ${v.vertraege.length === 1 ? 'Vertrag' : 'Verträge'}` : ''}</div>
              </button>
            {/each}
            <button class="grid w-28 shrink-0 place-items-center rounded-[var(--radius-card)] border border-dashed border-line p-3.5 text-center text-[14px] font-semibold text-muted active:bg-card-hi" onclick={() => (bereichNeuOffen = true)}>
              <span><span class="block text-[22px]">＋</span>Eigener Bereich</span>
            </button>
          {/if}
        </div>
      </div>

      {#if !trend || (trend.kategorien.length && trendReihe)}
        <div class="order-3">
          <h2 class="abschnitt">Verlauf je Kategorie</h2>
          <div class="karte p-5">
            {#if !trend}
              <Laden form="block" />
            {:else}
              <div class="-mx-5 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none]">
                {#each trend.kategorien as k (k.kategorie)}
                  <button
                    class="shrink-0 rounded-full px-3 py-1.5 text-[13px] font-semibold transition-colors {trendReihe.kategorie === k.kategorie ? 'bg-accent text-white' : 'bg-bg text-muted'}"
                    onclick={() => { trendKategorie = k.kategorie; trendMonat = null; }}>{k.kategorie}</button
                  >
                {/each}
              </div>
              <div class="mt-4 flex items-baseline justify-between">
                <span class="text-[13px] text-muted">{trendMonat ? monatName(trendMonat) : 'Ø pro Monat'}</span>
                <Amount wert={trendMonat ? trendReihe.werte[trend.monate.indexOf(trendMonat)] : trendReihe.schnitt} klasse="text-[20px] font-bold tracking-tight" />
              </div>
              <div class="relative mt-3 flex h-28 items-end gap-1">
                <div class="pointer-events-none absolute inset-x-0 border-t border-dashed border-faint/60" style="bottom: {(Number(trendReihe.schnitt) / trendMax) * 100}%"></div>
                {#each trend.monate as m, i (m)}
                  <button class="flex h-full flex-1 items-end justify-center rounded-lg {trendMonat === m ? 'bg-card-hi' : ''}" onclick={() => (trendMonat = trendMonat === m ? null : m)} aria-label={monatName(m)}>
                    <span class="w-2.5 rounded-full transition-[height] duration-200" style="height: {Math.max(2, (Number(trendReihe.werte[i]) / trendMax) * 100)}%; background: {kategorieFarbe[trendReihe.kategorie] ?? 'var(--color-accent)'}"></span>
                  </button>
                {/each}
              </div>
              <div class="mt-1 flex gap-1">
                {#each trend.monate as m (m)}
                  <span class="flex-1 text-center text-[10px] font-medium {trendMonat === m ? 'text-text' : 'text-muted'}">{monatName(m, true).slice(0, 3)}</span>
                {/each}
              </div>
              {#if trendMonat}
                <button class="knopf-sekundaer mt-3 w-full !py-2.5" onclick={() => trendBelege(trendReihe.kategorie, trendMonat!)}>
                  Buchungen {trendReihe.kategorie} · {monatName(trendMonat)}<ChevronRight size={17} />
                </button>
              {:else}
                <p class="mt-2 text-[12px] text-faint">Letzte zwölf Monate; die gestrichelte Linie ist der Durchschnitt (ohne den laufenden Monat). Monat antippen für die Buchungen.</p>
              {/if}
            {/if}
          </div>
        </div>
      {/if}

      <div class="order-3">
        <h2 class="abschnitt">Frag deine Zahlen</h2>
        <section class="karte p-5">
          {#if kiBereit === false}
            <p class="text-[14px] leading-relaxed text-muted">
              Dafür braucht es den Mistral-Schlüssel aus den <a href="#/einstellungen" class="text-accent">Einstellungen → Kategorien mit KI</a>.
            </p>
          {:else}
            <form class="flex gap-2" onsubmit={(e) => { e.preventDefault(); fragen(); }}>
              <input class="feld flex-1 !py-3 text-[15px]" placeholder="z. B. Wie viel für Restaurants im Sommer?" maxlength="300" bind:value={frage} />
              <button class="knopf-primaer !px-4 !py-3" disabled={fragt || frage.trim().length < 3}>{fragt ? '…' : 'Fragen'}</button>
            </form>
            {#if antwort}
              <div class="mt-4 rounded-2xl bg-bg p-4">
                <p class="text-[15px] leading-relaxed">{antwort.antwort}</p>
                {#if antwort.zeilen.length}
                  <div class="mt-3 divide-y divide-line text-[14px]">
                    {#each antwort.zeilen as z, i (i)}
                      {#if z.buchung_id}
                        <button class="flex w-full items-center justify-between gap-3 py-2 text-left" onclick={() => { detailId = z.buchung_id; detailOffen = true; }}>
                          <span class="min-w-0 truncate">{z.label}</span><Amount wert={z.betrag} klasse="shrink-0 font-medium" />
                        </button>
                      {:else}
                        <div class="flex items-center justify-between gap-3 py-2">
                          <span class="min-w-0 truncate">{z.monat ? monatName(z.monat) : z.label}</span><Amount wert={z.betrag} klasse="shrink-0 font-medium" />
                        </div>
                      {/if}
                    {/each}
                  </div>
                {/if}
                {#if antwort.verstanden}<p class="mt-3 text-[12px] text-faint">Verstanden als: {antwort.verstanden}</p>{/if}
              </div>
            {:else}
              <div class="mt-3 flex flex-wrap gap-2">
                {#each BEISPIELE as b (b)}
                  <button class="rounded-full bg-bg px-3 py-1.5 text-left text-[13px] text-muted active:bg-card-hi" onclick={() => fragen(b)}>{b}</button>
                {/each}
              </div>
            {/if}
            <p class="mt-3 flex gap-1.5 text-[12px] leading-relaxed text-faint">
              <Lock size={13} class="mt-0.5 shrink-0" />
              <span>An die KI gehen nur deine Frage und die Namen deiner Kategorien. Beträge, Buchungen und Empfänger bleiben auf deinem Server – dort wird gerechnet.</span>
            </p>
          {/if}
        </section>
      </div>
    </div>

    <div class="contents min-w-0 lg:block">
      <div class="order-2">
        <h2 class="abschnitt lg:!pt-1">Einnahmen und Ausgaben</h2>
        <section class="karte p-5">
          {#if !analyse}
            <span class="schimmer block h-11 rounded-2xl"></span>
            <div class="mt-5"><Laden form="block" /></div>
          {:else}
            <div class="mb-4 grid grid-cols-2 gap-1 rounded-2xl bg-bg p-1">
              {#each [['monat', 'Monat'], ['jahr', 'Jahr']] as [wert, label] (wert)}
                <button
                  class="rounded-xl py-2 text-[14px] font-semibold transition-colors {modus === wert ? 'bg-card-hi text-text' : 'text-muted'}"
                  aria-pressed={modus === wert}
                  onclick={() => modusWaehlen(wert as 'monat' | 'jahr')}>{label}</button
                >
              {/each}
            </div>
            <div class="flex items-center justify-between">
              <button class="grid size-9 place-items-center rounded-full text-accent active:bg-card-hi" onclick={() => schieben(-1)} aria-label={modus === 'jahr' ? 'Vorjahr' : 'Vormonat'}>
                <ChevronLeft size={22} />
              </button>
              <h3 class="text-[18px] font-bold">{zeitraumText}</h3>
              <button
                class="grid size-9 place-items-center rounded-full text-accent active:bg-card-hi disabled:opacity-25"
                onclick={() => schieben(1)}
                disabled={modus === 'jahr' ? analyse.jahr >= jetzt.getFullYear() : analyse.monat >= dieserMonat}
                aria-label={modus === 'jahr' ? 'Nächstes Jahr' : 'Nächster Monat'}><ChevronRight size={22} /></button
              >
            </div>
            <div class="mt-4 grid grid-cols-3 gap-2 text-center">
              <button class="rounded-2xl bg-bg py-3 active:bg-card-hi" onclick={() => belegeZeigen('einnahme')}>
                <div class="text-[12px] text-muted">Einnahmen</div>
                <Amount wert={analyse.einnahmen} farbig kurz klasse="text-[17px] font-semibold" />
              </button>
              <button class="rounded-2xl bg-bg py-3 active:bg-card-hi" onclick={() => belegeZeigen('ausgabe')}>
                <div class="text-[12px] text-muted">Ausgaben</div>
                <Amount wert={analyse.ausgaben} kurz klasse="text-[17px] font-semibold text-neg" />
              </button>
              <button class="rounded-2xl bg-bg py-3 active:bg-card-hi" onclick={() => belegeZeigen('gespart')}>
                <div class="text-[12px] text-muted">Gespart</div>
                <Amount wert={analyse.gespart} kurz klasse="text-[17px] font-semibold" />
              </button>
            </div>
            {#if analyse.vorjahr}
              <p class="mt-3 text-center text-[13px] text-muted">
                Vorjahr: <Amount wert={analyse.vorjahr.einnahmen} kurz /> Einnahmen, <Amount wert={analyse.vorjahr.ausgaben} kurz /> Ausgaben{#if veraenderung(analyse.ausgaben, analyse.vorjahr.ausgaben)}
                  {' '}(seitdem {veraenderung(analyse.ausgaben, analyse.vorjahr.ausgaben)}){/if}
              </p>
            {/if}
            <div class="mt-5">
              <MonatsBalken daten={analyse.verlauf} aktiv={analyse.monat} onwahl={monatLaden} schmal={modus === 'jahr'} />
            </div>
            <div class="mt-2 flex justify-center gap-5 text-[12px] text-muted">
              <span class="flex items-center gap-1.5"><span class="size-2 rounded-full bg-pos"></span>Einnahmen</span>
              <span class="flex items-center gap-1.5"><span class="size-2 rounded-full bg-neg"></span>Ausgaben</span>
            </div>
          {/if}
        </section>
      </div>

      <div class="order-2">
        <h2 class="abschnitt">Ausgaben nach Kategorie{#if analyse}<span class="ml-2 hidden text-[14px] font-medium tracking-normal text-muted sm:inline">{zeitraumText}</span>{/if}</h2>
        {#if unklar}
          <a href="#/unklar" class="mb-3 flex items-center gap-3 rounded-2xl bg-warn-soft px-4 py-3.5 text-warn">
            <span class="flex-1 text-[14px] leading-snug">
              <b class="font-semibold">{unklar} {unklar === 1 ? 'Buchung' : 'Buchungen'} zu klären</b> · Kategorien und Umbuchungen zuordnen
            </span>
            <ChevronRight size={18} class="shrink-0" />
          </a>
        {/if}
        {#if !analyse}
          <Laden form="liste" zeilen={KATEGORIEN_KURZ} />
        {:else}
          <!-- Torte und Liste gehören zusammen: eine Karte, dieselben Farben -->
          <div class="karte overflow-hidden">
            {#if analyse.kategorien.length}
              <div class="border-b border-line p-5">
                <KategorieTorte
                  stuecke={tortenstuecke}
                  gesamt={analyse.ausgaben}
                  bind:wahl={tortenWahl}
                  onwahl={(k) => (k === 'Übrige' ? belegeZeigen('ausgabe') : belegeZeigen('ausgabe', k))}
                />
              </div>
            {/if}
            {#each kategorienSichtbar as k (k.kategorie)}
              <button
                class="zeile {tortenWahl === k.kategorie ? 'bg-card-hi' : ''}"
                onclick={() => belegeZeigen('ausgabe', k.kategorie)}
                onpointerenter={(e) => e.pointerType === 'mouse' && (tortenWahl = k.kategorie)}
                onpointerleave={(e) => e.pointerType === 'mouse' && (tortenWahl = null)}
              >
                <KategorieAvatar kategorie={k.kategorie} groesse={40} />
                <div class="min-w-0 flex-1">
                  <div class="flex items-baseline justify-between gap-3">
                    <span class="truncate text-[16px]">{k.kategorie}</span>
                    <Amount wert={k.summe} klasse="text-[16px] font-medium" />
                  </div>
                  <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-line">
                    <div class="h-full rounded-full" style="width: {Math.max(2, k.anteil * 100)}%; background: {kategorieFarbe[k.kategorie]}"></div>
                  </div>
                  <div class="mt-1.5 text-[12px] text-muted">{k.anzahl} {k.anzahl === 1 ? 'Buchung' : 'Buchungen'} · {Math.round(k.anteil * 100)} %</div>
                </div>
                <ChevronRight size={18} class="shrink-0 text-faint" />
              </button>
              {#each k.unter ?? [] as u (u.kategorie)}
                <button class="flex w-full items-center gap-2.5 py-2 pl-[70px] pr-4 text-left text-[14px] active:bg-card-hi" onclick={() => belegeZeigen('ausgabe', u.kategorie)}>
                  <span>{emoji(u.kategorie)}</span>
                  <span class="min-w-0 flex-1 truncate text-muted">{u.kategorie} · {u.anzahl}×</span>
                  <Amount wert={u.summe} klasse="shrink-0" />
                  <ChevronRight size={15} class="shrink-0 text-faint" />
                </button>
              {/each}
            {:else}
              <div class="p-6 text-center text-[15px] text-muted">Keine Ausgaben in diesem {modus === 'jahr' ? 'Jahr' : 'Monat'}.</div>
            {/each}
            {#if kategorienMehr > 0 || alleKategorien}
              <button class="flex w-full items-center justify-center gap-1 border-t border-line py-3.5 text-[14px] font-semibold text-accent active:bg-card-hi" onclick={() => (alleKategorien = !alleKategorien)}>
                {#if alleKategorien}Weniger zeigen<ChevronUp size={17} />{:else}{kategorienMehr} weitere {kategorienMehr === 1 ? 'Kategorie' : 'Kategorien'} · <Amount wert={kategorienRest} kurz /><ChevronDown size={17} />{/if}
              </button>
            {/if}
          </div>
        {/if}
      </div>

      {#if analyse?.tags.length}
        <div class="order-2">
          <h2 class="abschnitt">Ausgaben nach Tag<span class="ml-2 hidden text-[14px] font-medium tracking-normal text-muted sm:inline">{zeitraumText}</span></h2>
          <div class="karte overflow-hidden">
            {#each analyse.tags as t (t.tag)}
              <button class="zeile" onclick={() => belegeZeigen('ausgabe', null, t.tag)}>
                <span class="grid size-10 shrink-0 place-items-center rounded-[14px] bg-accent-soft text-[17px] font-bold text-accent">#</span>
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[16px]">{t.tag}</span>
                  <span class="block text-[12px] text-muted">{t.anzahl} {t.anzahl === 1 ? 'Buchung' : 'Buchungen'}</span>
                </span>
                <Amount wert={t.summe} klasse="text-[16px] font-medium" />
                <ChevronRight size={18} class="shrink-0 text-faint" />
              </button>
            {/each}
          </div>
        </div>
      {/if}

      {#if analyse?.steuer?.length}
        <a href="#/sparen" class="karte order-2 mt-4 flex items-center gap-3 px-4 py-3.5 text-[15px]">
          <span class="flex-1">Spenden, Beiträge und Versicherungen {analyse.jahr} für die Steuererklärung</span>
          <span class="flex items-center gap-0.5 font-medium text-accent">Sparen<ChevronRight size={18} /></span>
        </a>
      {/if}
    </div>
  </div>
</div>

<Sheet bind:offen={belegeOffen} titel={belegeTitel}>
  {#if !belege}
    <Laden form="liste" />
  {:else if !belege.length}
    <p class="py-8 text-center text-[15px] text-muted">Keine Buchungen.</p>
  {:else}
    <div class="karte overflow-hidden">
      {#each belege as b (b.id)}
        <button class="zeile" onclick={() => { detailId = b.id; detailOffen = true; }}>
          <KategorieAvatar kategorie={b.kategorie} logo={b.logo} groesse={40} rund />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[16px]">{b.gegenpartei || b.verwendungszweck || b.buchungstext || 'Buchung'}</span>
            <span class="block truncate text-[13px] text-muted">{datumKurz(b.datum)} · {b.mein_betrag ? `dein Anteil ${euro(Math.abs(Number(b.mein_betrag)))}` : b.konto_name}</span>
          </span>
          <Amount wert={b.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
        </button>
      {/each}
    </div>
  {/if}
</Sheet>
<BereichSheet bind:offen={bereichNeuOffen} ongespeichert={(id) => gehe(`/bereich/${id}`)} />
<BuchungDetail bind:offen={detailOffen} id={detailId} ongeaendert={() => { belegeLaden(); if (analyse.monat) monatLaden(analyse.monat); else jahrLaden(analyse.jahr); }} />
