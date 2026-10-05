<script lang="ts">
  import { ArrowUpDown, CalendarDays, Check, ChevronRight, Hourglass, Plus, TrendingDown, TrendingUp, X } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import { slide } from 'svelte/transition';
  import Amount from '../components/Amount.svelte';
  import Header from '../components/Header.svelte';
  import IconKnopf from '../components/IconKnopf.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import KategorieTorte from '../components/KategorieTorte.svelte';
  import Sheet from '../components/Sheet.svelte';
  import { TORTENFARBEN } from '../lib/kategorien';
  import Laden from '../components/Laden.svelte';
  import VertragNeu from '../components/VertragNeu.svelte';
  import { api } from '../lib/api';
  import { euro, inTagen, monatName, TURNUS } from '../lib/format';
  import { gehe } from '../lib/router.svelte';
  import { fehler, merker, toast } from '../lib/store.svelte';

  // Gruppiert wird immer nach Zeitraum (monatlich, jährlich …) – sortiert wird nur innerhalb der Gruppe
  type Sortierung = 'betrag' | 'faelligkeit';
  const SORT_TEXT: Record<Sortierung, string> = { betrag: 'Betrag', faelligkeit: 'Fälligkeit' };

  let daten = $state<any>(null);
  let sortierung = $state<Sortierung>(merker.lesen('bp_sort') === 'faelligkeit' ? 'faelligkeit' : 'betrag');
  let inaktivOffen = $state(false);
  let neuOffen = $state(false);
  let ausgeblendet = $state<Record<string, boolean>>(JSON.parse(merker.lesen('bp_warn_aus') ?? '{}'));

  async function laden() {
    try {
      daten = await api('/contracts');
    } catch (e) {
      fehler(e);
    }
  }

  function sortWechseln() {
    sortierung = sortierung === 'betrag' ? 'faelligkeit' : 'betrag';
    merker.schreiben('bp_sort', sortierung);
  }

  function sortiert(liste: any[]) {
    const kopie = [...liste];
    if (sortierung === 'betrag') return kopie.sort((a, b) => Number(b.monatlich) - Number(a.monatlich));
    return kopie.sort((a, b) => a.naechste_faelligkeit.localeCompare(b.naechste_faelligkeit));
  }

  async function entfernen(c: any) {
    if (!confirm(`„${c.name}“ entfernen? BankPocket erkennt ihn dann nicht erneut.`)) return;
    try {
      await api(`/contracts/${c.id}`, { method: 'DELETE' });
      toast('Vertrag entfernt');
      laden();
    } catch (e) {
      fehler(e);
    }
  }

  // Erkannte Verträge sind zunächst Vorschläge: „Ja“ übernimmt sie, „Nein“ entfernt sie dauerhaft
  async function antworten(c: any, ja: boolean) {
    try {
      if (ja) await api(`/contracts/${c.id}/bestaetigen`, { method: 'POST' });
      else await api(`/contracts/${c.id}`, { method: 'DELETE' });
      toast(ja ? 'Als Vertrag übernommen' : 'Kein Vertrag – wird nicht mehr vorgeschlagen');
      laden();
    } catch (e) {
      fehler(e);
    }
  }

  function warnungAus(c: any) {
    ausgeblendet[`${c.id}|${c.naechste_faelligkeit}`] = true;
    merker.schreiben('bp_warn_aus', JSON.stringify(ausgeblendet));
  }

  // Analyse der Verträge: Was kommt im Schnitt pro Monat rein, was ist durch Verträge und Sparpläne gebunden,
  // was bleibt frei – und wie verteilen sich die Verträge auf Kategorien.
  let aufteilungOffen = $state(false);
  let offeneKategorie = $state<string | null>(null);
  const FREI = 'Frei verfügbar';
  const bilanz = $derived.by(() => {
    if (!daten) return null;
    const einnahmen = daten.einnahmen.flatMap((s: any) => s.vertraege).reduce((n: number, c: any) => n + Number(c.monatlich), 0);
    const vertraege = Number(daten.ausgaben_monatlich);
    const sparen = Number(daten.sparen_monatlich);
    const anteil = (x: number) => (einnahmen > 0 ? Math.round((x / einnahmen) * 100) : null);
    return { einnahmen, vertraege, sparen, frei: einnahmen - vertraege - sparen, anteilVertraege: anteil(vertraege), anteilSparen: anteil(sparen) };
  });
  const aufteilung = $derived.by(() => {
    if (!daten || !bilanz) return [];
    const vertraege = [...daten.ausgaben, ...daten.sparen].flatMap((s: any) => s.vertraege);
    const gebunden = vertraege.reduce((n: number, c: any) => n + Number(c.monatlich), 0);
    // Bezugsgröße ist das Einkommen – so zeigt die Torte auch, was frei bleibt. Ohne erkanntes Einkommen
    // (oder wenn die Verträge es übersteigen) teilen sich nur die Verträge den Kreis.
    const basis = bilanz.frei > 0 ? bilanz.einnahmen : gebunden;
    const gruppen = new Map<string, any[]>();
    for (const c of vertraege) gruppen.set(c.kategorie, [...(gruppen.get(c.kategorie) ?? []), c]);
    const stuecke: any[] = [...gruppen.entries()]
      .map(([kategorie, liste]) => {
        const summe = liste.reduce((n, c) => n + Number(c.monatlich), 0);
        return { kategorie, summe, anteil: basis ? summe / basis : 0,
          vertraege: liste.sort((a, b) => Number(b.monatlich) - Number(a.monatlich)) };
      })
      .sort((a, b) => b.summe - a.summe)
      .map((k, i) => ({ ...k, farbe: TORTENFARBEN[i % TORTENFARBEN.length] }));
    if (bilanz.frei > 0) stuecke.push({ kategorie: FREI, summe: bilanz.frei, anteil: bilanz.frei / basis, vertraege: [], farbe: 'var(--color-spur)' });
    return stuecke;
  });

  const ausgaben = $derived(daten ? daten.ausgaben.flatMap((s: any) => s.vertraege) : []);
  const einnahmen = $derived(daten ? daten.einnahmen.flatMap((s: any) => s.vertraege) : []);

  onMount(laden);
</script>

{#snippet zeile(c: any)}
  <div
    class="zeile cursor-pointer !flex-col !items-stretch !gap-0"
    role="link"
    tabindex="0"
    onclick={() => gehe(`/vertrag/${c.id}`)}
    onkeydown={(e) => e.key === 'Enter' && gehe(`/vertrag/${c.id}`)}
  >
    <div class="flex items-center gap-3.5">
      <KategorieAvatar kategorie={c.kategorie} logo={c.logo} />
      <div class="min-w-0 flex-1">
        <div class="truncate text-[17px]">{c.name}</div>
        <div class="truncate text-[14px] text-muted">
          {c.kategorie}{#if c.anteil_prozent < 100} · dein Anteil {c.anteil_prozent} %{/if}{#if sortierung === 'faelligkeit'} · {inTagen(c.naechste_faelligkeit)}{/if}
        </div>
      </div>
      <div class="text-right">
        <Amount wert={Math.abs(Number(c.mein_betrag))} farbig={c.typ === 'einnahme'} klasse="text-[17px] font-medium" />
        {#if c.turnus !== 'jaehrlich'}
          <div class="text-[12px] text-muted"><Amount wert={Math.abs(Number(c.jaehrlich))} /> / Jahr</div>
        {/if}
      </div>
    </div>
    {#if (c.betrag_gestiegen || c.betrag_gesunken) && c.status !== 'ueberfaellig'}
      <!-- gut (grün): Kosten sinken, Einnahmen oder Sparrate steigen – sonst Warnfarbe -->
      {@const gut = c.typ === 'einnahme' || c.sparen ? c.betrag_gestiegen : c.betrag_gesunken}
      <div class="mt-2 pl-[58px]">
        <span class="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] font-medium {gut ? 'bg-accent-soft text-pos' : 'bg-warn-soft text-warn'}">
          {#if c.betrag_gestiegen}<TrendingUp size={13} />{:else}<TrendingDown size={13} />{/if}
          {c.typ === 'einnahme' || c.sparen
            ? (c.betrag_gestiegen ? 'Gestiegen' : 'Gesunken')
            : (c.betrag_gestiegen ? 'Teurer geworden' : 'Günstiger geworden')} · vorher {euro(Math.abs(Number(c.vorheriger_betrag)))}
        </span>
      </div>
    {/if}
    {#if c.status === 'ueberfaellig' && !ausgeblendet[`${c.id}|${c.naechste_faelligkeit}`]}
      <div class="mt-3 flex items-center gap-2">
        <span class="mr-auto flex items-center gap-1.5 whitespace-nowrap text-[14px] font-medium text-warn">
          <Hourglass size={16} /> {c.tage_ueberfaellig} Tage überfällig
        </span>
        <button class="pill-accent whitespace-nowrap !py-1.5 text-[13px]" onclick={(e) => { e.stopPropagation(); entfernen(c); }}>Vertrag entfernen</button>
        <button
          class="grid size-7 shrink-0 place-items-center rounded-full bg-card-hi text-muted"
          onclick={(e) => { e.stopPropagation(); warnungAus(c); }}
          aria-label="Hinweis ausblenden"><X size={15} /></button
        >
      </div>
    {/if}
  </div>
{/snippet}

{#snippet sektionen(liste: any[], typ: string)}
  {#each liste as s (s.turnus)}
    <div class="flex items-baseline justify-between px-1 pb-2.5 pt-6">
      <h2 class="text-[20px] font-bold tracking-tight">{TURNUS[s.turnus]} <span class="font-semibold text-muted">({s.anzahl})</span></h2>
      <Amount wert={s.summe} farbig={typ === 'einnahme'} klasse="text-[15px] text-muted" />
    </div>
    <div class="karte overflow-hidden">
      {#each sortiert(s.vertraege) as c (c.id)}{@render zeile(c)}{/each}
    </div>
  {/each}
{/snippet}

<div class="px-4">
  <Header titel="Verträge">
    {#snippet aktionen()}
      <IconKnopf label="Kalender" href="#/kalender"><CalendarDays size={22} /></IconKnopf>
      <IconKnopf label="Vertrag hinzufügen" onclick={() => (neuOffen = true)}><Plus size={24} /></IconKnopf>
    {/snippet}
  </Header>

  {#if !daten}
    <Laden />
  {:else}
    <button class="karte block w-full p-5 text-left active:bg-card-hi" onclick={() => (aufteilungOffen = true)} disabled={!aufteilung.length}>
      <div class="flex items-center justify-between text-[15px] font-semibold text-muted">
        Verträge und Sparpläne
        {#if aufteilung.length}<span class="flex items-center gap-0.5 font-medium text-accent">Analyse<ChevronRight size={18} /></span>{/if}
      </div>
      <div class="mt-2 flex flex-wrap items-baseline gap-x-2">
        <span class="text-[30px] font-bold">Ø</span>
        <Amount wert={Number(daten.ausgaben_monatlich) + Number(daten.sparen_monatlich)} klasse="text-[30px] font-bold tracking-tight" />
        <span class="text-[17px] text-muted">/ Monat</span>
      </div>
      {#if Number(daten.sparen_monatlich) > 0}
        <div class="mt-1 text-[14px] text-muted">davon Ø <Amount wert={daten.sparen_monatlich} /> pro Monat in Sparpläne</div>
      {/if}
    </button>

    {#if daten.vorschlaege.length}
      <h2 class="abschnitt !pb-1">Stimmt das? <span class="font-semibold text-muted">({daten.vorschlaege.length})</span></h2>
      <p class="px-1 pb-3 text-[14px] text-muted">
        BankPocket hat wiederkehrende Zahlungen gefunden. Sie zählen erst mit, wenn du sie als Vertrag bestätigst.
      </p>
      <div class="karte overflow-hidden lg:grid lg:grid-cols-2">
        {#each daten.vorschlaege as c (c.id)}
          <div class="zeile !flex-col !items-stretch !gap-3 lg:!border-t-0">
            <a class="flex items-center gap-3.5" href="#/vertrag/{c.id}">
              <KategorieAvatar kategorie={c.kategorie} logo={c.logo} />
              <div class="min-w-0 flex-1">
                <div class="truncate text-[17px]">{c.name}</div>
                <div class="truncate text-[14px] text-muted">
                  {TURNUS[c.turnus]} · {c.vorkommen} Zahlungen ·
                  <span class={c.sicherheit >= 75 ? 'text-pos' : c.sicherheit >= 55 ? '' : 'text-warn'}>
                    {c.sicherheit >= 75 ? 'ziemlich sicher' : c.sicherheit >= 55 ? 'wahrscheinlich' : 'unsicher'}
                  </span>
                </div>
              </div>
              <Amount wert={Math.abs(Number(c.mein_betrag))} farbig={c.typ === 'einnahme'} klasse="text-[17px] font-medium" />
            </a>
            <div class="grid grid-cols-2 gap-2">
              <button class="knopf-sekundaer !py-2.5" onclick={() => antworten(c, false)}><X size={17} /> Nein</button>
              <button class="knopf-primaer !py-2.5" onclick={() => antworten(c, true)}><Check size={17} /> Ja, Vertrag</button>
            </div>
          </div>
        {/each}
      </div>
    {/if}

    {#if ausgaben.length || einnahmen.length || daten.sparen.length}
      <button class="karte mt-3 flex w-full items-center justify-center gap-2 py-3.5 text-[16px] active:bg-card-hi" onclick={sortWechseln}>
        Sortieren nach <b class="font-semibold">{SORT_TEXT[sortierung]}</b><ArrowUpDown size={17} />
      </button>
      <!-- Am PC: links alles, was abgeht (Verträge, darunter Sparpläne), rechts nur das Einkommen -->
      <div class="lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-8">
        <div>
          {@render sektionen(daten.ausgaben, 'ausgabe')}
          {#if daten.sparen.length}
            <div class="mt-4 flex items-baseline justify-between px-1">
              <h2 class="abschnitt !px-0 !pb-0 !pt-3">Sparen</h2>
              <span class="text-[15px] text-muted">Ø <Amount wert={daten.sparen_monatlich} /> / Monat</span>
            </div>
            {@render sektionen(daten.sparen, 'ausgabe')}
          {/if}
        </div>
        {#if einnahmen.length}
          <div>
            <h2 class="abschnitt mt-4 !pb-0 lg:mt-0">Einnahmen</h2>
            {@render sektionen(daten.einnahmen, 'einnahme')}
          </div>
        {/if}
      </div>
    {:else}
      <div class="karte mt-4 p-6 text-center text-[15px] text-muted">
        Noch keine Verträge. BankPocket findet wiederkehrende Zahlungen automatisch – Abos, Miete, Versicherungen und
        dein Gehalt – und fragt dich dann, ob es wirklich Verträge sind.
      </div>
    {/if}

    <div class="karte mt-8 overflow-hidden">
      <button class="zeile" onclick={() => (neuOffen = true)}>
        <span class="flex-1 text-[17px] text-accent">Vertrag hinzufügen</span><ChevronRight size={20} class="text-accent" />
      </button>
      <button class="zeile" onclick={() => (inaktivOffen = !inaktivOffen)} aria-expanded={inaktivOffen}>
        <span class="flex-1 text-[17px] text-accent">Inaktive Verträge ({daten.inaktiv.length})</span>
        <ChevronRight size={20} class="text-accent transition-transform {inaktivOffen ? 'rotate-90' : ''}" />
      </button>
      {#if inaktivOffen}
        <div transition:slide={{ duration: 180 }}>
          {#each daten.inaktiv as c (c.id)}
            <a class="zeile opacity-60" href="#/vertrag/{c.id}">
              <KategorieAvatar kategorie={c.kategorie} logo={c.logo} groesse={36} />
              <span class="flex-1 truncate text-[16px]">{c.name}</span>
              <Amount wert={Math.abs(Number(c.mein_betrag))} klasse="text-[15px]" />
            </a>
          {:else}
            <div class="zeile text-[15px] text-muted">Keine inaktiven Verträge.</div>
          {/each}
        </div>
      {/if}
      {#if daten.basierend_seit}
        <div class="zeile text-[15px] text-muted">Basierend auf Buchungen seit {monatName(daten.basierend_seit.slice(0, 7))}</div>
      {/if}
    </div>
  {/if}
</div>

<VertragNeu bind:offen={neuOffen} ongespeichert={laden} />

<Sheet bind:offen={aufteilungOffen} titel="Analyse der Verträge">
  {#if daten && bilanz && aufteilung.length}
    <div class="karte divide-y divide-line text-[16px]">
      <div class="px-4 pb-2 pt-3.5 text-[15px] font-semibold text-muted">Durchschnittlich pro Monat</div>
      <div class="flex items-center justify-between px-4 py-3">
        <span>Einnahmen</span><Amount wert={bilanz.einnahmen} farbig klasse="font-medium" />
      </div>
      <div class="flex items-center justify-between gap-2 px-4 py-3">
        <span class="flex items-center gap-2">Verträge
          {#if bilanz.anteilVertraege !== null}<span class="rounded-lg bg-card-hi px-2 py-0.5 text-[13px] text-muted">{bilanz.anteilVertraege} %</span>{/if}
        </span>
        <Amount wert={-bilanz.vertraege} vorzeichen klasse="font-medium" />
      </div>
      <div class="flex items-center justify-between gap-2 px-4 py-3">
        <span class="flex items-center gap-2">Sparen
          {#if bilanz.anteilSparen !== null}<span class="rounded-lg bg-card-hi px-2 py-0.5 text-[13px] text-muted">{bilanz.anteilSparen} %</span>{/if}
        </span>
        <Amount wert={-bilanz.sparen} vorzeichen klasse="font-medium" />
      </div>
      <div class="flex items-center justify-between px-4 py-3.5 font-bold">
        <span>{FREI}</span>
        <span class={bilanz.frei < 0 ? 'text-neg' : 'text-pos'}><Amount wert={bilanz.frei} vorzeichen={bilanz.frei < 0} /></span>
      </div>
    </div>
    {#if !bilanz.einnahmen}
      <p class="mt-2 px-1 text-[13px] text-muted">Noch kein regelmäßiges Einkommen bestätigt – darum fehlt der Vergleich mit den Einnahmen.</p>
    {/if}

    <h3 class="px-1 pb-3 pt-6 text-[17px] font-semibold">Verträge pro Kategorie</h3>
    <KategorieTorte
      stuecke={aufteilung}
      titel={bilanz.frei > 0 ? FREI : 'gebunden pro Monat'}
      gesamt={bilanz.frei > 0 ? bilanz.frei : bilanz.vertraege + bilanz.sparen}
      bind:wahl={offeneKategorie}
    />
    <p class="mt-2 text-center text-[13px] text-muted">Jährliche, vierteljährliche und wöchentliche Verträge sind auf den Monat umgerechnet</p>
    <div class="karte mt-4 overflow-hidden">
      <div class="flex justify-between px-4 pb-1 pt-3 text-[13px] font-semibold text-muted"><span>Kategorie</span><span>Monatlich</span></div>
      {#if bilanz.einnahmen > 0}
        <div class="zeile">
          <span class="h-8 w-1 shrink-0 rounded-full bg-pos"></span>
          <span class="min-w-0 flex-1 text-[16px]">Einkommen</span>
          <Amount wert={bilanz.einnahmen} farbig klasse="text-[16px] font-medium" />
          <span class="w-[18px] shrink-0"></span>
        </div>
      {/if}
      {#each aufteilung as k (k.kategorie)}
        <button class="zeile" disabled={!k.vertraege.length} onclick={() => (offeneKategorie = offeneKategorie === k.kategorie ? null : k.kategorie)} aria-expanded={offeneKategorie === k.kategorie}>
          <span class="h-8 w-1 shrink-0 rounded-full" style="background: {k.farbe}"></span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[16px]">{k.kategorie}</span>
            <span class="block text-[12px] text-muted">
              {#if k.vertraege.length}{k.vertraege.length} {k.vertraege.length === 1 ? 'Vertrag' : 'Verträge'} · {/if}{Math.round(k.anteil * 100)} %{bilanz.frei > 0 ? ' vom Einkommen' : ''}
            </span>
          </span>
          <Amount wert={k.kategorie === FREI ? k.summe : -k.summe} vorzeichen={k.kategorie !== FREI} klasse="text-[16px] font-medium" />
          {#if k.vertraege.length}
            <ChevronRight size={18} class="shrink-0 text-faint transition-transform {offeneKategorie === k.kategorie ? 'rotate-90' : ''}" />
          {:else}<span class="w-[18px] shrink-0"></span>{/if}
        </button>
        {#if offeneKategorie === k.kategorie && k.vertraege.length}
          <div class="border-t border-line bg-card-hi/50" transition:slide={{ duration: 160 }}>
            {#each k.vertraege as c (c.id)}
              <a class="flex items-center gap-3 px-4 py-2.5 pl-8" href="#/vertrag/{c.id}" onclick={() => (aufteilungOffen = false)}>
                <span class="min-w-0 flex-1 truncate text-[14px]">{c.name}</span>
                <span class="text-[12px] text-muted">{TURNUS[c.turnus]}</span>
                <Amount wert={c.monatlich} klasse="text-[14px]" />
              </a>
            {/each}
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</Sheet>
