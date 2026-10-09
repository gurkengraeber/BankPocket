<script lang="ts">
  import { BellRing, CalendarDays, Check, ChevronRight, Hourglass, Pencil, Plus, Search, TrendingDown, TrendingUp, Undo2 } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import BuchungDetail from '../components/BuchungDetail.svelte';
  import ArtenWahl from '../components/ArtenWahl.svelte';
  import Auswahl from '../components/Auswahl.svelte';
  import DatumFeld from '../components/DatumFeld.svelte';
  import KategorieWahl from '../components/KategorieWahl.svelte';
  import Sheet from '../components/Sheet.svelte';
  import VersicherungSheet from '../components/VersicherungSheet.svelte';
  import { VERWALTUNG } from '../lib/versicherung';
  import Header from '../components/Header.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import Laden from '../components/Laden.svelte';
  import { api } from '../lib/api';
  import { datum, euro, inTagen, TURNUS } from '../lib/format';
  import { emoji } from '../lib/kategorien';
  import { kategorieNeu, kategorienLaden } from '../lib/kategorieNeu';
  import { gehe } from '../lib/router.svelte';
  import { fehler, toast } from '../lib/store.svelte';

  let { id }: { id: number } = $props();

  const METHODE: Record<string, string> = {
    sepa: 'SEPA-Lastschrift (Mandat)',
    gegenpartei: 'Empfänger, Betrag und Rhythmus',
    paypal: 'PayPal-Händler',
  };

  let v = $state<any>(null);
  let kategorien = $state<{ ausgabe: string[]; einnahme: string[] } | null>(null);
  let bearbeiten = $state(false);
  let neuerName = $state('');

  async function laden() {
    try {
      v = await api(`/contracts/${id}`);
    } catch (e) {
      fehler(e);
    }
  }

  // Zahlungen ansehen und weitere Buchungen von Hand zuordnen
  let detailId = $state<number | null>(null);
  let detailOffen = $state(false);
  let zuordnenOffen = $state(false);
  let suche = $state('');
  let treffer = $state<any[] | null>(null);
  let suchTimer: ReturnType<typeof setTimeout> | undefined;

  async function suchen() {
    try {
      const p = new URLSearchParams({ limit: '80' });
      if (suche.trim()) p.set('suche', suche.trim());
      const d = await api(`/buchungen?${p}`);
      // nur Buchungen in dieselbe Richtung, die noch nicht zu diesem Vertrag gehören
      treffer = d.buchungen.filter((b: any) => b.contract_id !== id && b.betrag > 0 === (v.typ === 'einnahme'));
    } catch (e) {
      fehler(e);
    }
  }

  function zuordnenOeffnen() {
    suche = v.name;
    treffer = null;
    zuordnenOffen = true;
    suchen();
  }

  async function zuordnen(b: any) {
    try {
      await api(`/buchungen/${b.id}`, { method: 'PATCH', body: { contract_id: id } });
      toast('Buchung zugeordnet');
      await Promise.all([laden(), suchen()]);
    } catch (e) {
      fehler(e);
    }
  }

  // Rückzahlung eintragen: Geld, das der Anbieter zurücküberwiesen hat (Erstattung, Gutschrift) – die Buchung wird
  // als Rückzahlung markiert und gehört dann zu diesem Vertrag. Er kostet entsprechend weniger.
  let rzOffen = $state(false);
  let rzSuche = $state('');
  let rzTreffer = $state<any[] | null>(null);
  let rzTimer: ReturnType<typeof setTimeout> | undefined;

  async function rzSuchen() {
    try {
      const p = new URLSearchParams({ limit: '80', eingaenge: 'true' });
      if (rzSuche.trim()) p.set('suche', rzSuche.trim());
      const d = await api(`/buchungen?${p}`);
      rzTreffer = d.buchungen.filter((b: any) => b.contract_id !== id);
    } catch (e) {
      fehler(e);
    }
  }

  function rzOeffnen() {
    rzSuche = v.name;
    rzTreffer = null;
    rzOffen = true;
    rzSuchen();
  }

  async function rzEintragen(b: any) {
    try {
      const alt = Number(v.betrag);
      await api(`/buchungen/${b.id}`, { method: 'PATCH', body: { rueckzahlung: true, kategorie: v.kategorie, contract_id: id } });
      rzOffen = false;
      await laden();
      toast(Number(v.betrag) !== alt ? `Rückzahlung eingetragen – der Vertrag kostet jetzt ${euro(Math.abs(Number(v.betrag)))}` : 'Rückzahlung eingetragen');
    } catch (e) {
      fehler(e);
    }
  }

  // Betrag von Hand: bleibt stehen, bis man ihn wieder „automatisch“ stellt. Vorschläge zum Antippen.
  let betragOffen = $state(false);
  let betragText = $state('');
  const zahl = (text: string) => Number(text.trim().replace(/[€\s]/g, '').replace(/\.(?=\d{3}(\D|$))/g, '').replace(',', '.'));
  const eingabe = (x: number) => x.toFixed(2).replace('.', ',');

  function betragOeffnen() {
    betragText = eingabe(Math.abs(Number(v.betrag)));
    betragOffen = true;
  }

  async function betragSpeichern(e: Event) {
    e.preventDefault();
    const wert = zahl(betragText);
    if (!(wert > 0)) return;
    await aendern({ betrag: Math.round(wert * 100) / 100 });
    betragOffen = false;
  }

  async function betragAutomatisch() {
    await aendern({ betrag_automatisch: true });
    betragOffen = false;
  }

  // Vertragsdaten: Art, Laufzeit, Kündigungsfrist – trägt man selbst ein, die Bank weiß davon nichts.
  // Alles Übliche per Knopf; getippt wird nur, wo es nicht anders geht.
  const ARTEN: [string, string][] = ['Abo', 'Mitgliedschaft', 'Mobilfunk', 'Internet', 'Strom / Gas', 'Miete', 'Spende', 'Kredit / Rate', 'Sparplan'].map((a) => [a, a]);
  const FRISTEN: [string, string][] = [['', 'Keine'], ['1-tage', '1 Tag'], ['14-tage', '14 Tage'], ['4-wochen', '4 Wochen'], ['1-monate', '1 Monat'], ['6-wochen', '6 Wochen'], ['3-monate', '3 Monate'], ['6-monate', '6 Monate']];
  const VERLAENGERUNG: [number, string][] = [[0, 'Gar nicht'], [1, '1 Monat'], [3, '3 Monate'], [6, '6 Monate'], [12, '1 Jahr'], [24, '2 Jahre']];
  const ANTEILE: [number, string][] = [[100, 'Ich allein'], [50, 'Die Hälfte'], [33, 'Ein Drittel'], [25, 'Ein Viertel']];
  const jahr = new Date().getFullYear();
  let datenOffen = $state(false);
  let versOffen = $state(false);
  let versicherungsarten = $state<string[]>([]);
  let f = $state({ art: '', frist: '', frist_wert: '', frist_einheit: 'monate', laufzeit_bis: '', verlaengerung_monate: 0, vertragsnummer: '', notiz: '', anteil: 100 });

  function datenOeffnen() {
    const frist = v.frist_wert ? `${v.frist_wert}-${v.frist_einheit || 'monate'}` : '';
    f = { art: v.art || v.art_vorschlag || '', frist: !frist || FRISTEN.some(([w]) => w === frist) ? frist : 'andere', frist_wert: v.frist_wert ? String(v.frist_wert) : '',
      frist_einheit: v.frist_einheit || 'monate', laufzeit_bis: v.laufzeit_bis ?? '', verlaengerung_monate: v.verlaengerung_monate ?? 0,
      vertragsnummer: v.vertragsnummer, notiz: v.notiz, anteil: v.anteil_prozent };
    datenOffen = true;
  }

  async function datenSpeichern(e: Event) {
    e.preventDefault();
    const [wert, einheit] = f.frist === 'andere' ? [f.frist_wert, f.frist_einheit] : f.frist.split('-');
    await aendern({ art: f.art, frist_wert: Number(wert) || null, frist_einheit: einheit || '', laufzeit_bis: f.laufzeit_bis || null,
      verlaengerung_monate: Number(f.verlaengerung_monate) || null, vertragsnummer: f.vertragsnummer, notiz: f.notiz,
      anteil_prozent: Math.min(100, Math.max(1, Math.round(Number(f.anteil) || 100))) });
    datenOffen = false;
  }

  const heuteIso = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

  async function aendern(daten: Record<string, string | number | boolean | null>) {
    try {
      v = { ...v, ...(await api(`/contracts/${id}`, { method: 'PATCH', body: daten })) };
      toast('Gespeichert');
    } catch (e) {
      fehler(e);
    }
  }

  async function kategorieAnlegen(name: string) {
    try {
      kategorien = await kategorieNeu(name, v.typ);
      await aendern({ kategorie: name });
    } catch (e) {
      fehler(e);
    }
  }

  async function entfernen() {
    if (!confirm(`„${v.name}“ entfernen? BankPocket erkennt ihn dann nicht erneut.`)) return;
    await api(`/contracts/${id}`, { method: 'DELETE' }).catch(fehler);
    toast('Vertrag entfernt');
    gehe('/vertraege');
  }

  onMount(() => {
    laden();
    kategorienLaden().then((k) => (kategorien = k));
    api('/versicherungen').then((d) => (versicherungsarten = d.arten)).catch(() => {});
  });
</script>

<div class="px-4">
  <Header titel={v?.name ?? 'Vertrag'} gross={false} zurueckZu="#/vertraege" />

  {#if !v}
    <Laden form="detail" />
  {:else}
    <div class="flex flex-col items-center pb-2 pt-3 text-center">
      <KategorieAvatar kategorie={v.kategorie} logo={v.logo} groesse={72} />
      {#if bearbeiten}
        <form class="mt-4 flex w-full gap-2" onsubmit={(e) => { e.preventDefault(); bearbeiten = false; aendern({ name: neuerName }); }}>
          <input class="feld flex-1 text-center text-[20px] font-semibold" bind:value={neuerName} />
          <button class="knopf-primaer !px-4">OK</button>
        </form>
      {:else}
        <button class="mt-4 flex items-center gap-2 text-[24px] font-bold tracking-tight" onclick={() => { neuerName = v.name; bearbeiten = true; }}>
          {v.name}<Pencil size={16} class="text-muted" />
        </button>
      {/if}
      <button class="mt-1 flex items-center gap-2" onclick={betragOeffnen} aria-label="Betrag ändern">
        <Amount wert={Math.abs(Number(v.betrag))} farbig={v.typ === 'einnahme'} klasse="text-[38px] font-bold tracking-tight" />
        <Pencil size={16} class="text-muted" />
      </button>
      <div class="text-[15px] text-muted">
        {TURNUS[v.turnus]}{#if v.turnus !== 'monatlich'} · Ø <Amount wert={v.monatlich} /> pro Monat{/if}
      </div>
      <div class="mt-3 grid w-full max-w-sm grid-cols-2 gap-2 text-left">
        <div class="rounded-2xl bg-card px-3.5 py-2.5">
          <div class="text-[12px] text-muted">Aufs Jahr gerechnet</div>
          <Amount wert={Math.abs(Number(v.jaehrlich))} klasse="text-[17px] font-semibold" />
          <div class="text-[11px] text-faint">aktueller Betrag</div>
        </div>
        <div class="rounded-2xl bg-card px-3.5 py-2.5">
          <div class="text-[12px] text-muted">Letzte 12 Monate</div>
          <Amount wert={Math.abs(Number(v.gezahlt_12_monate))} klasse="text-[17px] font-semibold" />
          <div class="text-[11px] text-faint">tatsächlich gebucht{Number(v.rueckzahlungen) > 0 ? ', abzüglich Rückzahlungen' : ''}</div>
        </div>
      </div>
      <div class="mt-3 flex flex-wrap justify-center gap-2">
        {#if v.anteil_prozent < 100}
          <span class="pill bg-accent-soft text-accent">Dein Anteil {v.anteil_prozent} % · {euro(Math.abs(Number(v.mein_betrag)))}</span>
        {/if}
        {#if v.betrag_fix}
          <span class="pill bg-card-hi text-muted">Betrag von dir festgelegt</span>
        {/if}
        {#if v.gekuendigt_zum}
          <span class="pill bg-card-hi text-muted"><Check size={14} /> Gekündigt zum {datum(v.gekuendigt_zum)}</span>
        {/if}
        {#if v.status === 'ueberfaellig'}
          <span class="pill bg-warn-soft text-warn"><Hourglass size={14} /> {v.tage_ueberfaellig} Tage überfällig</span>
        {:else if v.status === 'inaktiv'}
          <span class="pill bg-card-hi text-muted">Inaktiv</span>
        {/if}
        {#if v.betrag_gestiegen || v.betrag_gesunken}
          {@const gut = v.typ === 'einnahme' || v.sparen ? v.betrag_gestiegen : v.betrag_gesunken}
          <span class="pill {gut ? 'bg-accent-soft text-pos' : 'bg-warn-soft text-warn'}">
            {#if v.betrag_gestiegen}<TrendingUp size={14} />{:else}<TrendingDown size={14} />{/if}
            {v.betrag_gestiegen ? 'gestiegen' : 'gesunken'} · vorher {euro(Math.abs(Number(v.vorheriger_betrag)))}
          </span>
        {/if}
      </div>
    </div>

    <div class="karte mt-6 divide-y divide-line text-[16px]">
      <a class="flex items-center justify-between gap-3 px-4 py-3.5 active:bg-card-hi" href="#/kalender">
        <span class="shrink-0 text-muted">{v.typ === 'einnahme' ? 'Nächster Eingang' : 'Nächste Zahlung'}</span>
        <span class="flex items-center gap-1.5 whitespace-nowrap text-right">{datum(v.naechste_faelligkeit)}<span class="text-muted">· {inTagen(v.naechste_faelligkeit)}</span><CalendarDays size={16} class="shrink-0 text-faint" /></span>
      </a>
      {#if kategorien}
        <!-- eintippen filtert die Liste; was es noch nicht gibt (z. B. „Abo“), lässt sich direkt anlegen -->
        <div class="px-4 py-3">
          <label class="mb-1.5 block text-muted" for="v-kategorie">Kategorie</label>
          <KategorieWahl
            id="v-kategorie"
            wert={v.kategorie}
            optionen={v.typ === 'einnahme' ? kategorien.einnahme : kategorien.ausgabe}
            onwahl={(k) => aendern({ kategorie: k })}
            onneu={kategorieAnlegen}
          />
        </div>
      {/if}
      <div class="flex items-center justify-between gap-4 px-4 py-3.5">
        <span class="text-muted">Erkannt über</span>
        <span class="text-right">{v.quelle === 'manuell' ? 'Von dir angelegt' : (METHODE[v.methode] ?? v.methode)}</span>
      </div>
    </div>

    <h2 class="abschnitt">Vertragsdaten</h2>
    <div class="karte divide-y divide-line text-[16px]">
      {#if v.kuendigung && !v.kuendigung.jederzeit && !v.kuendigung.verpasst}
        <div class="px-4 py-3.5">
          <div class="flex items-center justify-between gap-4">
            <span class="text-muted">Kündigen bis</span>
            <span class={v.kuendigung.tage <= 30 ? 'font-semibold text-warn' : ''}>{datum(v.kuendigung.kuendigen_bis)} <span class="font-normal text-muted">· {inTagen(v.kuendigung.kuendigen_bis)}</span></span>
          </div>
          <div class="mt-1 text-[13px] text-muted">
            {v.verlaengerung_monate ? `Sonst läuft der Vertrag bis ${datum(v.kuendigung.ende)} weiter.` : `Der Vertrag endet am ${datum(v.kuendigung.ende)}.`}
          </div>
        </div>
      {:else if v.kuendigung?.jederzeit}
        <div class="flex items-center justify-between gap-4 px-4 py-3.5">
          <span class="text-muted">Kündbar</span>
          <span class="text-right">jederzeit · Frist {v.kuendigung.frist}<span class="block text-[13px] text-muted">heute gekündigt endet er am {datum(v.kuendigung.ende)}</span></span>
        </div>
      {:else if v.kuendigung?.verpasst}
        <div class="flex items-center justify-between gap-4 px-4 py-3.5"><span class="text-muted">Laufzeit</span><span>endete am {datum(v.kuendigung.ende)}</span></div>
      {/if}
      {#each [['Art', v.art || v.art_vorschlag], ['Mein Anteil', v.anteil_prozent < 100 ? `${v.anteil_prozent} %` : ''], ['Kündigungsfrist', v.kuendigung?.frist], ['Vertragsnummer', v.vertragsnummer]] as [label, wert] (label)}
        {#if wert}
          <div class="flex items-center justify-between gap-4 px-4 py-3.5"><span class="text-muted">{label}</span><span class="truncate text-right">{wert}</span></div>
        {/if}
      {/each}
      {#if v.notiz}<div class="whitespace-pre-line px-4 py-3.5 text-[15px] text-muted">{v.notiz}</div>{/if}
      {#if v.kategorie === 'Versicherung'}
        <button class="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left" onclick={() => (versOffen = true)}>
          <span class="text-muted">Verwaltet über</span>
          <span class="flex min-w-0 items-center gap-1.5 {v.verwaltet_ueber ? '' : 'text-accent'}">
            <span class="truncate">{v.verwaltet_ueber ? [VERWALTUNG[v.verwaltet_ueber], v.verwaltet_name].filter(Boolean).join(' · ') : 'Makler, App, direkt …'}</span><ChevronRight size={18} class="shrink-0" />
          </span>
        </button>
      {/if}
      <button class="flex w-full items-center justify-between px-4 py-3.5 text-accent" onclick={datenOeffnen}>
        <span>{v.kuendigung || v.art || v.vertragsnummer || v.notiz ? 'Vertragsdaten bearbeiten' : 'Art, Laufzeit und Kündigungsfrist eintragen'}</span>
        <ChevronRight size={18} />
      </button>
      {#if v.typ === 'ausgabe' && v.gekuendigt_zum}
        <div class="flex items-center gap-3 px-4 py-3">
          <Check size={20} class="shrink-0 text-pos" />
          <span class="min-w-0 flex-1">Gekündigt zum {datum(v.gekuendigt_zum)}<span class="block text-[13px] text-muted">Danach rechnet BankPocket nicht mehr mit Abbuchungen.</span></span>
          <button class="shrink-0 text-[14px] font-medium text-accent" onclick={() => aendern({ gekuendigt_zum: null })}>Zurücknehmen</button>
        </div>
      {:else if v.typ === 'ausgabe'}
        <button class="flex w-full items-center gap-3 px-4 py-3 text-left" onclick={() => aendern({ kuendigen: !v.kuendigen })} aria-pressed={v.kuendigen}>
          <BellRing size={20} class="shrink-0 {v.kuendigen ? 'text-accent' : 'text-muted'}" />
          <span class="min-w-0 flex-1">
            <span class="block">Will ich kündigen</span>
            <span class="block text-[13px] text-muted">
              {v.kuendigung?.kuendigen_bis ? 'Erinnert 30, 7 und 1 Tag vor dem letzten Termin' : 'Erinnert eine Woche vor der nächsten Abbuchung'}
            </span>
          </span>
          <span class="relative h-7 w-12 shrink-0 rounded-full transition-colors {v.kuendigen ? 'bg-accent' : 'bg-line'}">
            <span class="absolute top-0.5 size-6 rounded-full bg-white shadow transition-all {v.kuendigen ? 'left-[22px]' : 'left-0.5'}"></span>
          </span>
        </button>
        <button class="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left text-accent" onclick={() => aendern({ gekuendigt_zum: v.kuendigung?.ende ?? heuteIso() })}>
          <span>Ist gekündigt<span class="block text-[13px] text-muted">zum {datum(v.kuendigung?.ende ?? heuteIso())}{v.kuendigung ? '' : ' – trag Laufzeit und Frist ein, dann stimmt das Datum'}</span></span>
          <Check size={18} />
        </button>
      {/if}
    </div>

    <h2 class="abschnitt">Zahlungen{#if v.zahlungen.length} <span class="font-semibold text-muted">({v.zahlungen.length}) · {euro(Math.abs(Number(v.gezahlt_gesamt)))}</span>{/if}</h2>
    <div class="karte overflow-hidden">
      {#each v.zahlungen as z (z.id)}
        <button class="zeile" onclick={() => { detailId = z.id; detailOffen = true; }}>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 text-[16px]">{datum(z.datum)}{#if z.rueckzahlung}<span class="pill bg-accent-soft text-accent"><Undo2 size={13} /> Rückzahlung</span>{/if}</div>
            <div class="truncate text-[13px] text-muted">{z.konto_name}{z.verwendungszweck ? ` · ${z.verwendungszweck}` : ''}</div>
          </div>
          <Amount wert={z.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
          <ChevronRight size={18} class="shrink-0 text-faint" />
        </button>
      {/each}
      <button class="zeile" onclick={zuordnenOeffnen}>
        <span class="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent"><Plus size={20} /></span>
        <span class="flex-1 text-[16px] text-accent">Buchung zuordnen</span>
      </button>
      {#if v.typ === 'ausgabe'}
        <button class="zeile" onclick={rzOeffnen}>
          <span class="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent"><Undo2 size={20} /></span>
          <span class="min-w-0 flex-1 text-left">
            <span class="block text-[16px] text-accent">Rückzahlung eintragen</span>
            <span class="block text-[13px] text-muted">Geld, das du von {v.name} zurückbekommen hast</span>
          </span>
        </button>
      {/if}
    </div>

    <button class="knopf-gefahr mt-8 w-full" onclick={entfernen}>Vertrag entfernen</button>
  {/if}
</div>

<BuchungDetail bind:offen={detailOffen} id={detailId} ongeaendert={laden} />
<VersicherungSheet bind:offen={versOffen} vertrag={v} ongespeichert={laden} />

<Sheet bind:offen={datenOffen} titel="Vertragsdaten">
  <form onsubmit={datenSpeichern} class="space-y-5">
    <div>
      <div class="label">{v?.kategorie === 'Versicherung' ? 'Was ist versichert?' : 'Was ist es?'}</div>
      {#if v?.kategorie === 'Versicherung' && versicherungsarten.length}
        <ArtenWahl arten={versicherungsarten} gewaehlt={f.art.split(',').map((x) => x.trim()).filter(Boolean)} onaendern={(liste) => (f.art = liste.join(', '))} />
        <p class="mt-1.5 text-[13px] text-muted">Mehrere wählen, wenn der Vertrag mehrere Versicherungen bündelt (z. B. Hausrat mit Fahrrad).</p>
      {:else}
        <Auswahl optionen={ARTEN} bind:wert={f.art} andere platzhalter="z. B. Zeitungsabo" />
      {/if}
    </div>
    {#if v?.typ === 'ausgabe'}
      <div>
        <div class="label">Wer zahlt?</div>
        <Auswahl optionen={ANTEILE} bind:wert={f.anteil} andere einheit="%" platzhalter="Mein Anteil" />
        <p class="mt-1.5 text-[13px] text-muted">
          {#if v && Number(f.anteil) > 0 && Number(f.anteil) < 100}
            Dein Anteil: {euro(Math.abs(Number(v.betrag)) * Number(f.anteil) / 100)} von {euro(Math.abs(Number(v.betrag)))}. Überall – Analysen, Budgets, frei verfügbar – zählt dann nur dieser Teil.
          {:else}
            Teilst du dir den Vertrag (WG-Miete, Familien-Abo), zählt überall nur dein Anteil.
          {/if}
        </p>
      </div>
    {/if}
    <div>
      <div class="label">Kündigungsfrist</div>
      <Auswahl optionen={[...FRISTEN, ['andere', 'Andere']]} bind:wert={f.frist} />
      {#if f.frist === 'andere'}
        <div class="mt-2 grid grid-cols-2 gap-3">
          <input class="feld" inputmode="numeric" placeholder="Anzahl" bind:value={f.frist_wert} aria-label="Kündigungsfrist: Anzahl" />
          <Auswahl optionen={[['tage', 'Tage'], ['wochen', 'Wochen'], ['monate', 'Monate']]} bind:wert={f.frist_einheit} />
        </div>
      {/if}
    </div>
    <div>
      <label class="label" for="vd-bis">Läuft bis</label>
      <Auswahl optionen={[['', 'Kein festes Ende'], [`${jahr}-12-31`, `Ende ${jahr}`], [`${jahr + 1}-12-31`, `Ende ${jahr + 1}`]]} bind:wert={f.laufzeit_bis} />
      <div class="mt-2"><DatumFeld id="vd-bis" bind:wert={f.laufzeit_bis} /></div>
      <p class="mt-1.5 text-[13px] text-muted">Ende der aktuellen Laufzeit – oder über das Kalendersymbol wählen. Ohne festes Ende ist der Vertrag jederzeit kündbar.</p>
    </div>
    {#if f.laufzeit_bis}
      <div>
        <div class="label">Danach verlängert er sich um</div>
        <Auswahl optionen={VERLAENGERUNG} bind:wert={f.verlaengerung_monate} />
      </div>
    {/if}
    <div><label class="label" for="vd-nr">Vertrags- oder Kundennummer</label><input id="vd-nr" class="feld" bind:value={f.vertragsnummer} /></div>
    <div><label class="label" for="vd-notiz">Notiz</label><textarea id="vd-notiz" class="feld min-h-20" placeholder="z. B. was abgedeckt ist, Selbstbeteiligung, wie man kündigt" bind:value={f.notiz}></textarea></div>
    <button class="knopf-primaer w-full">Speichern</button>
  </form>
</Sheet>

<Sheet bind:offen={zuordnenOffen} titel="Buchung zuordnen">
  <label class="relative mb-3 block">
    <Search size={18} class="absolute left-4 top-1/2 -translate-y-1/2 text-faint" />
    <input
      class="feld !rounded-full !py-3 pl-11"
      placeholder="Empfänger, Verwendungszweck oder Tag"
      type="search"
      bind:value={suche}
      oninput={() => { clearTimeout(suchTimer); suchTimer = setTimeout(suchen, 300); }}
    />
  </label>
  {#if !treffer}
    <Laden form="liste" />
  {:else if !treffer.length}
    <p class="py-8 text-center text-[15px] text-muted">Keine passenden Buchungen gefunden.</p>
  {:else}
    <div class="karte overflow-hidden">
      {#each treffer as b (b.id)}
        <button class="zeile" onclick={() => zuordnen(b)}>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[16px]">{b.gegenpartei || b.verwendungszweck || b.buchungstext || 'Buchung'}</span>
            <span class="block truncate text-[13px] text-muted">{datum(b.datum)} · {b.konto_name}{b.contract_id ? ' · gehört zu anderem Vertrag' : ''}</span>
          </span>
          <Amount wert={b.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
          <Plus size={18} class="shrink-0 text-accent" />
        </button>
      {/each}
    </div>
  {/if}
</Sheet>

<Sheet bind:offen={rzOffen} titel="Rückzahlung eintragen">
  <p class="-mt-2 mb-3 text-[14px] text-muted">
    Wähle den Geldeingang, der von {v?.name} zurückkam. Er zählt dann nicht als Einnahme, sondern mindert, was dich der Vertrag kostet.
  </p>
  <label class="relative mb-3 block">
    <Search size={18} class="absolute left-4 top-1/2 -translate-y-1/2 text-faint" />
    <input
      class="feld !rounded-full !py-3 pl-11"
      placeholder="Absender, Verwendungszweck oder Tag"
      type="search"
      bind:value={rzSuche}
      oninput={() => { clearTimeout(rzTimer); rzTimer = setTimeout(rzSuchen, 300); }}
    />
  </label>
  {#if !rzTreffer}
    <Laden form="liste" />
  {:else if !rzTreffer.length}
    <p class="py-8 text-center text-[15px] text-muted">Keine Geldeingänge gefunden. Lösche den Suchbegriff, um alle zu sehen.</p>
  {:else}
    <div class="karte overflow-hidden">
      {#each rzTreffer as b (b.id)}
        <button class="zeile" onclick={() => rzEintragen(b)}>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[16px]">{b.gegenpartei || b.verwendungszweck || b.buchungstext || 'Buchung'}</span>
            <span class="block truncate text-[13px] text-muted">{datum(b.datum)} · {b.konto_name}{b.rueckzahlung ? ' · schon als Rückzahlung markiert' : ''}{b.contract_id ? ' · gehört zu anderem Vertrag' : ''}</span>
          </span>
          <Amount wert={b.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
          <Plus size={18} class="shrink-0 text-accent" />
        </button>
      {/each}
    </div>
  {/if}
</Sheet>

<Sheet bind:offen={betragOffen} titel="Betrag ändern">
  <form onsubmit={betragSpeichern} class="space-y-4">
    <div>
      <label class="label" for="bt-betrag">Betrag je Zahlung ({TURNUS[v?.turnus]})</label>
      <div class="relative">
        <input id="bt-betrag" class="feld pr-10 text-2xl font-semibold" inputmode="decimal" placeholder="0,00" bind:value={betragText} />
        <span class="absolute right-4 top-1/2 -translate-y-1/2 text-xl text-muted">€</span>
      </div>
    </div>
    {#if v?.letzte_zahlung_betrag || v?.letzte_zahlung_netto}
      <div class="flex flex-wrap gap-2">
        {#if v.letzte_zahlung_betrag}
          <button type="button" class="pill-accent" onclick={() => (betragText = eingabe(Math.abs(Number(v.letzte_zahlung_betrag))))}>Zuletzt gezahlt: {euro(Math.abs(Number(v.letzte_zahlung_betrag)))}</button>
        {/if}
        {#if v.letzte_zahlung_netto}
          <button type="button" class="pill-accent" onclick={() => (betragText = eingabe(Math.abs(Number(v.letzte_zahlung_netto))))}>Nach Rückzahlung: {euro(Math.abs(Number(v.letzte_zahlung_netto)))}</button>
        {/if}
      </div>
    {/if}
    <p class="text-[13px] text-muted">
      {v?.betrag_fix ? 'Dieser Betrag gilt, bis du ihn wieder automatisch erkennen lässt – auch wenn sich die Abbuchung ändert.' : 'BankPocket bestimmt den Betrag aus den Buchungen. Mit einem eigenen Betrag bleibt er so, auch wenn sich die Abbuchung ändert.'}
    </p>
    <button class="knopf-primaer w-full" disabled={!(zahl(betragText) > 0)}>Speichern</button>
    {#if v?.betrag_fix}
      <button type="button" class="w-full py-2 text-[15px] font-medium text-accent" onclick={betragAutomatisch}>Wieder automatisch erkennen</button>
    {/if}
  </form>
</Sheet>
