<script lang="ts">
  import { ChevronRight, Landmark, PiggyBank, Plus, Receipt, Repeat, X } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import Auswahl from '../components/Auswahl.svelte';
  import BankAvatar from '../components/BankAvatar.svelte';
  import BuchungDetail from '../components/BuchungDetail.svelte';
  import Header from '../components/Header.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import Laden from '../components/Laden.svelte';
  import Sheet from '../components/Sheet.svelte';
  import VertragNeu from '../components/VertragNeu.svelte';
  import { api } from '../lib/api';
  import { datumKurz, euro, inTagen, monatName, TURNUS } from '../lib/format';
  import { fehler, merker, toast } from '../lib/store.svelte';

  // Vier Bereiche, oben als Kacheln mit der jeweils wichtigsten Zahl – antippen wechselt den Bereich darunter
  type Bereich = 'quote' | 'plaene' | 'erspartes' | 'steuern';
  let bereich = $state<Bereich>((merker.lesen('bp_sparen') as Bereich) || 'quote');
  function bereichWaehlen(b: Bereich) {
    bereich = b;
    merker.schreiben('bp_sparen', b);
  }

  let daten = $state<any>(null);
  let fenster = $state(Number(merker.lesen('bp_sparfenster') ?? 6));
  let gewaehlt = $state<string | null>(null);
  let neuOffen = $state(false);

  const prozent = (q: number | null) => (q === null ? '–' : `${Math.round(q * 100)} %`);
  const max = $derived(Math.max(1, ...(daten?.verlauf ?? []).map((v: any) => Math.abs(Number(v.uebrig)))));
  const maxAngelegt = $derived(Math.max(1, ...(daten?.verlauf ?? []).map((v: any) => Math.abs(Number(v.angelegt)))));
  const monat = $derived(daten?.verlauf.find((v: any) => v.monat === gewaehlt) ?? null);
  const imFenster = (m: string) => !!daten?.von && m >= daten.von && m <= daten.bis;
  // Schnitt je Monat über das gewählte Fenster
  const schnittWerte = $derived.by(() => {
    const volle = (daten?.verlauf ?? []).filter((v: any) => imFenster(v.monat));
    const mittel = (feld: string) => (volle.length ? volle.reduce((n: number, v: any) => n + Number(v[feld]), 0) / volle.length : 0);
    return { einnahmen: mittel('einnahmen'), ausgaben: mittel('ausgaben'), angelegt: mittel('angelegt') };
  });

  // Hinter jeder Zahl stehen Buchungen: eines Monats, des Schnitt-Zeitraums oder eines Jahres (Steuerliste)
  type Filter = { titel: string; monat?: string; monate?: number; jahr?: number; kategorie?: string; empfaenger?: string; steuern?: boolean };
  const ARTEN: [string, string][] = [['einnahme', 'Einnahmen'], ['ausgabe', 'Ausgaben'], ['gespart', 'Angelegt']];
  let filter = $state<Filter | null>(null);
  let art = $state('ausgabe');
  let belegeOffen = $state(false);
  let belege = $state<any[] | null>(null);
  let detailId = $state<number | null>(null);
  let detailOffen = $state(false);

  async function belegeLaden() {
    if (!filter) return;
    const p = new URLSearchParams({ art });
    for (const k of ['monat', 'monate', 'jahr', 'kategorie', 'empfaenger', 'steuern'] as const) if (filter[k]) p.set(k, String(filter[k]));
    if (filter.jahr) p.set('steuerliste', 'true'); // was aus der Steuerliste genommen wurde, fehlt hier
    try {
      belege = (await api(`/analysen/buchungen?${p}`)).buchungen;
    } catch (e) {
      fehler(e);
    }
  }

  function zeigen(f: Filter, a: string) {
    filter = f;
    art = a;
    belege = null;
    belegeOffen = true;
    belegeLaden();
  }

  const schnitt = $derived.by<Filter | null>(() => {
    if (!daten?.von) return null;
    const [j1, m1] = daten.von.split('-').map(Number);
    const [j2, m2] = daten.bis.split('-').map(Number);
    return { titel: `${monatName(daten.von, true)} – ${monatName(daten.bis)}`, monat: daten.von, monate: (j2 - j1) * 12 + m2 - m1 + 1 };
  });

  // Steuern: Spenden, Beiträge und Versicherungen eines Jahres je Empfänger
  const STEUER_TITEL: Record<string, string> = { Spenden: 'Spenden', Mitgliedschaft: 'Mitgliedsbeiträge (z. B. Gewerkschaft)', Versicherung: 'Versicherungen' };
  const diesesJahr = new Date().getFullYear();
  let steuerJahr = $state(diesesJahr);
  let steuer = $state<any[] | null>(null);

  // Steuerzahlungen und -erstattungen erkennt der Server am Empfänger, die übrigen Gruppen an der Kategorie
  const steuerFilter = (st: any): Filter => ({ titel: `${st.kategorie} ${steuerJahr}`, jahr: steuerJahr, ...(st.steuern ? { steuern: true } : { kategorie: st.kategorie }) });
  const steuerSumme = $derived((steuer ?? []).filter((st) => st.art !== 'einnahme').reduce((n, st) => n + Number(st.summe), 0));

  // „Das war etwas anderes“: Buchung aus der Steuerliste nehmen, ohne sie sonst anzufassen
  async function ausSteuerliste(b: any) {
    try {
      await api(`/buchungen/${b.id}`, { method: 'PATCH', body: { steuer: 'nein' } });
      toast('Aus der Steuerliste genommen – an der Buchung lässt es sich zurückstellen');
      await Promise.all([belegeLaden(), steuerLaden(steuerJahr)]);
    } catch (e) {
      fehler(e);
    }
  }

  async function steuerLaden(jahr: number) {
    steuerJahr = jahr;
    try {
      steuer = (await api(`/analysen/jahr?jahr=${jahr}`)).steuer;
    } catch (e) {
      fehler(e);
    }
  }

  async function laden() {
    try {
      daten = await api(`/sparen?fenster=${fenster}`);
    } catch (e) {
      fehler(e);
    }
  }

  function fensterWaehlen(n: number) {
    fenster = n;
    merker.schreiben('bp_sparfenster', String(n));
    laden();
  }

  const konten = $derived((daten?.gruppen ?? []).flatMap((g: any) => g.konten.filter((k: any) => k.aktiv).map((k: any) => ({ ...k, gruppe: g.name }))));

  onMount(() => {
    laden();
    steuerLaden(diesesJahr);
  });
</script>

{#snippet kachel(id: Bereich, Icon: any, titel: string, wert: string, unter: string)}
  <button
    class="rounded-2xl border p-3.5 text-left transition-colors {bereich === id ? 'border-accent bg-accent-soft' : 'border-line bg-card active:bg-card-hi'}"
    aria-pressed={bereich === id}
    onclick={() => bereichWaehlen(id)}
  >
    <div class="flex items-center gap-1.5 text-[13px] font-semibold {bereich === id ? 'text-accent' : 'text-muted'}"><Icon size={15} />{titel}</div>
    <div class="mt-1.5 truncate text-[20px] font-bold tracking-tight">{wert}</div>
    <div class="truncate text-[12px] text-muted">{unter}</div>
  </button>
{/snippet}

<div class="px-4">
  <Header titel="Sparen" />

  {#if !daten}
    <Laden form="kacheln" />
  {:else}
    <div class="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
      {@render kachel('quote', PiggyBank, 'Sparquote', prozent(daten.quote), daten.monate ? `Ø ${euro(daten.uebrig_monatlich, { kurz: true, vorzeichen: true })} im Monat` : 'noch zu wenig Daten')}
      {@render kachel('plaene', Repeat, 'Sparpläne', euro(daten.sparplaene_monatlich, { kurz: true }), `pro Monat · ${daten.sparplaene.length} ${daten.sparplaene.length === 1 ? 'Plan' : 'Pläne'}`)}
      {@render kachel('erspartes', Landmark, 'Erspartes', euro(daten.erspartes, { kurz: true }), `${konten.length} ${konten.length === 1 ? 'Konto' : 'Konten'}`)}
      {@render kachel('steuern', Receipt, 'Steuern', steuer ? euro(steuerSumme, { kurz: true }) : '…', `Spenden, Beiträge, Steuern ${steuerJahr}`)}
    </div>

    <div class="mx-auto mt-5 lg:max-w-[640px]">
      {#if bereich === 'quote'}
        <section class="karte p-5">
          <h2 class="text-[18px] font-bold">Was bleibt übrig?</h2>
          <div class="mt-2.5 flex items-center gap-2.5 text-[13px] text-muted">
            Schnitt über
            <Auswahl optionen={[[3, '3 Monate'], [6, '6 Monate'], [11, '11 Monate']]} bind:wert={fenster} onwahl={fensterWaehlen} />
          </div>
          <div class="mt-3 flex flex-wrap items-baseline gap-x-2.5">
            <span class="text-[38px] font-bold tracking-tight {daten.quote !== null && daten.quote < 0 ? 'text-neg' : ''}">{prozent(daten.quote)}</span>
            <span class="text-[15px] text-muted">{daten.monate ? `vom Einkommen · ${schnitt?.titel}` : 'noch zu wenig Daten'}</span>
          </div>
          {#if daten.monate && schnitt}
            <div class="mt-4 grid grid-cols-3 gap-2 text-center">
              {#each [['einnahme', 'Einnahmen', schnittWerte.einnahmen], ['ausgabe', 'Ausgaben', schnittWerte.ausgaben], ['gespart', 'Angelegt', schnittWerte.angelegt]] as [a, label, wert] (a)}
                <button class="rounded-2xl bg-card-hi py-2.5 active:brightness-95" onclick={() => zeigen(schnitt, a as string)}>
                  <div class="text-[12px] text-muted">Ø {label}</div>
                  <Amount {wert} kurz klasse="text-[15px] font-semibold {a === 'einnahme' ? 'text-pos' : a === 'ausgabe' ? 'text-neg' : ''}" />
                </button>
              {/each}
            </div>
          {/if}

          <div class="mt-6 flex h-36 items-stretch gap-1">
            {#each daten.verlauf as v (v.monat)}
              {@const hoehe = Math.max(3, (Math.abs(Number(v.uebrig)) / max) * 100)}
              <button
                class="flex flex-1 flex-col rounded-lg transition-colors {gewaehlt === v.monat ? 'bg-card-hi' : ''} {imFenster(v.monat) ? '' : 'opacity-45'}"
                onclick={() => (gewaehlt = gewaehlt === v.monat ? null : v.monat)}
                aria-label="{monatName(v.monat)}: {prozent(v.quote)}"
              >
                <span class="flex flex-1 items-end justify-center">
                  {#if Number(v.uebrig) >= 0}<span class="w-2.5 rounded-full bg-pos" style="height: {hoehe}%"></span>{/if}
                </span>
                <span class="h-px bg-line"></span>
                <span class="flex flex-1 items-start justify-center">
                  {#if Number(v.uebrig) < 0}<span class="w-2.5 rounded-full bg-neg" style="height: {hoehe}%"></span>{/if}
                </span>
                <span class="pb-0.5 text-[10px] font-medium {gewaehlt === v.monat ? 'text-text' : 'text-muted'}">{monatName(v.monat, true).slice(0, 3)}</span>
              </button>
            {/each}
          </div>
          {#if monat}
            <div class="mt-3 text-center text-[14px]">
              <b class="font-semibold">{monatName(monat.monat)}</b>: <Amount wert={monat.uebrig} vorzeichen kurz /> übrig ({prozent(monat.quote)})
            </div>
            <div class="mt-2 grid grid-cols-3 gap-2 text-center">
              {#each [['einnahme', 'Einnahmen', monat.einnahmen], ['ausgabe', 'Ausgaben', monat.ausgaben], ['gespart', 'Angelegt', monat.angelegt]] as [a, label, wert] (a)}
                <button class="rounded-2xl bg-bg py-2.5 active:bg-card-hi" onclick={() => zeigen({ titel: monatName(monat.monat), monat: monat.monat }, a)}>
                  <div class="text-[12px] text-muted">{label}</div>
                  <Amount {wert} kurz klasse="text-[15px] font-semibold {a === 'einnahme' ? 'text-pos' : a === 'ausgabe' ? 'text-neg' : ''}" />
                </button>
              {/each}
            </div>
          {:else}
            <p class="mt-2 text-center text-[13px] text-muted">Einnahmen minus Ausgaben je Monat – Monat antippen, dann zu den Buchungen. Blasse Monate zählen nicht in den Schnitt.</p>
          {/if}
        </section>
      {:else if bereich === 'plaene'}
        <div class="karte overflow-hidden">
          {#each daten.sparplaene as p (p.id)}
            <a class="zeile" href="#/vertrag/{p.id}">
              <KategorieAvatar kategorie="Sparen" groesse={40} />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-[16px]">{p.name}</span>
                <span class="block truncate text-[13px] text-muted">{TURNUS[p.turnus]} · nächste Ausführung {inTagen(p.naechste_faelligkeit)}</span>
              </span>
              <span class="shrink-0 text-right">
                <Amount wert={Math.abs(Number(p.betrag))} klasse="block text-[16px] font-medium" />
                {#if p.turnus !== 'monatlich'}<span class="block text-[12px] text-muted">{euro(p.monatlich, { kurz: true })} / Monat</span>{/if}
              </span>
              <ChevronRight size={18} class="shrink-0 text-faint" />
            </a>
          {:else}
            <div class="p-6 text-center text-[15px] text-muted">Noch kein Sparplan bestätigt – erkannte Sparpläne findest du unter Verträge.</div>
          {/each}
          <button class="zeile border-t border-line" onclick={() => (neuOffen = true)}>
            <span class="grid size-10 shrink-0 place-items-center rounded-[14px] bg-accent-soft text-accent"><Plus size={20} /></span>
            <span class="flex-1 text-[16px] text-accent">Sparplan eintragen</span>
          </button>
        </div>

        <h2 class="abschnitt">Angelegt je Monat</h2>
        <div class="karte p-5">
          <div class="flex h-28 items-end gap-1">
            {#each daten.verlauf as v (v.monat)}
              <button class="flex h-full flex-1 items-end justify-center rounded-lg active:bg-card-hi" onclick={() => zeigen({ titel: monatName(v.monat), monat: v.monat }, 'gespart')} aria-label="{monatName(v.monat)}: {euro(v.angelegt)} angelegt">
                <span class="w-2.5 rounded-full {Number(v.angelegt) < 0 ? 'bg-neg' : 'bg-accent'}" style="height: {Math.max(3, (Math.abs(Number(v.angelegt)) / maxAngelegt) * 100)}%"></span>
              </button>
            {/each}
          </div>
          <div class="mt-1 flex gap-1">
            {#each daten.verlauf as v (v.monat)}<span class="flex-1 text-center text-[10px] font-medium text-muted">{monatName(v.monat, true).slice(0, 3)}</span>{/each}
          </div>
          <p class="mt-2 text-[12px] text-faint">Käufe minus Verkäufe – einen Balken antippen zeigt die Buchungen des Monats.</p>
        </div>
      {:else if bereich === 'erspartes'}
        <div class="karte overflow-hidden">
          {#each konten as k (k.id)}
            <a class="zeile" href="#/konto/{k.id}">
              <BankAvatar quelle={k.quelle} name={k.name} />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-[16px]">{k.name}</span>
                <span class="block text-[13px] text-muted">{k.gruppe === 'Crypto' ? 'Krypto' : k.typ === 'depot' ? 'Depot' : 'Sparkonto'}</span>
              </span>
              <Amount wert={k.saldo} klasse="text-[16px] font-medium" />
              <ChevronRight size={18} class="shrink-0 text-faint" />
            </a>
          {:else}
            <div class="p-6 text-center text-[15px] text-muted">Noch kein Sparkonto, Depot oder Krypto-Konto verbunden.</div>
          {/each}
          <a class="zeile border-t border-line" href="#/analysen">
            <span class="flex-1 text-[16px] text-accent">Vermögensverlauf ansehen</span><ChevronRight size={18} class="text-accent" />
          </a>
          <a class="zeile border-t border-line" href="#/konto-neu">
            <span class="flex-1 text-[16px] text-accent">Konto hinzufügen</span><ChevronRight size={18} class="text-accent" />
          </a>
        </div>
      {:else}
        <div class="mb-3 flex items-center justify-between gap-3 px-1">
          <span class="text-[15px] text-muted">Für die Steuererklärung</span>
          <Auswahl optionen={[[diesesJahr - 1, String(diesesJahr - 1)], [diesesJahr, String(diesesJahr)]]} bind:wert={steuerJahr} onwahl={steuerLaden} />
        </div>
        {#if steuer?.length}
          {#each steuer as st (st.kategorie)}
            <div class="karte mb-3 overflow-hidden">
              <button class="flex w-full items-center gap-3 px-4 py-3.5 text-left active:bg-card-hi" onclick={() => zeigen(steuerFilter(st), st.art ?? 'ausgabe')}>
                <KategorieAvatar kategorie={st.steuern ? 'Gebühren & Steuern' : st.kategorie} groesse={36} />
                <span class="flex-1 text-[16px] font-semibold">{STEUER_TITEL[st.kategorie] ?? st.kategorie}</span>
                <Amount wert={st.summe} klasse="text-[16px] font-semibold" />
                <ChevronRight size={18} class="shrink-0 text-faint" />
              </button>
              {#each st.empfaenger as e (e.name)}
                <button class="flex w-full items-center gap-3 border-t border-line px-4 py-2.5 text-left text-[15px] active:bg-card-hi" onclick={() => zeigen({ ...steuerFilter(st), titel: `${e.name} ${steuerJahr}`, empfaenger: e.name }, st.art ?? 'ausgabe')}>
                  <span class="min-w-0 flex-1 truncate">{e.name}</span>
                  <span class="shrink-0 text-[13px] text-muted">{e.anzahl}×</span>
                  <Amount wert={e.summe} klasse="shrink-0" />
                  <ChevronRight size={16} class="shrink-0 text-faint" />
                </button>
              {/each}
            </div>
          {/each}
          <p class="px-1 text-[13px] leading-relaxed text-muted">
            Was du {steuerJahr} gespendet, an Beiträgen und Versicherungen und ans Finanzamt gezahlt hast – zum Nachschlagen. Was davon
            absetzbar ist, hängt vom Einzelfall ab; für Spenden brauchst du die Bescheinigung des Empfängers bzw. den Kontoauszug.
          </p>
        {:else if steuer}
          <div class="karte p-6 text-center text-[15px] text-muted">Keine Spenden, Beiträge oder Versicherungen in {steuerJahr}.</div>
        {:else}
          <Laden form="liste" />
        {/if}
      {/if}
    </div>
  {/if}
</div>

<VertragNeu bind:offen={neuOffen} ongespeichert={laden} kategorieVorgabe="Sparen" />

<Sheet bind:offen={belegeOffen} titel={filter?.titel ?? ''}>
  {#if filter && !filter.kategorie && !filter.steuern}
    <div class="mb-3 grid grid-cols-3 gap-1 rounded-2xl bg-card p-1">
      {#each ARTEN as [a, label] (a)}
        <button class="rounded-xl py-2 text-[14px] font-semibold {art === a ? 'bg-card-hi text-text' : 'text-muted'}" onclick={() => { art = a; belege = null; belegeLaden(); }}>{label}</button>
      {/each}
    </div>
  {/if}
  {#if !belege}
    <Laden form="liste" />
  {:else if !belege.length}
    <p class="py-8 text-center text-[15px] text-muted">Keine Buchungen.</p>
  {:else}
    <div class="mb-2 flex justify-between px-1 text-[13px] text-muted">
      <span>{belege.length} {belege.length === 1 ? 'Buchung' : 'Buchungen'}</span>
      <Amount wert={belege.reduce((n, b) => n + Number(b.mein_betrag ?? b.betrag), 0)} vorzeichen />
    </div>
    <div class="karte overflow-hidden">
      {#each belege as b (b.id)}
        <div class="flex items-center">
          <button class="zeile min-w-0 flex-1 {filter?.jahr ? '!pr-1' : ''}" onclick={() => { detailId = b.id; detailOffen = true; }}>
            <KategorieAvatar kategorie={b.kategorie} logo={b.logo} groesse={40} rund />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[16px]">{b.gegenpartei || b.verwendungszweck || b.buchungstext || 'Buchung'}</span>
              <span class="block truncate text-[13px] text-muted">{datumKurz(b.datum)} · {b.mein_betrag ? `dein Anteil ${euro(Math.abs(Number(b.mein_betrag)))}` : b.konto_name}</span>
            </span>
            <Amount wert={b.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
          </button>
          {#if filter?.jahr}
            <button class="grid size-11 shrink-0 place-items-center text-muted active:text-neg" onclick={() => ausSteuerliste(b)} aria-label="Aus der Steuerliste nehmen"><X size={18} /></button>
          {/if}
        </div>
      {/each}
    </div>
    {#if filter?.jahr}<p class="mt-3 text-[13px] text-muted">Das Kreuz nimmt eine Buchung aus der Steuerliste – sie bleibt sonst unverändert und zählt weiter als Ausgabe.</p>{/if}
  {/if}
</Sheet>
<BuchungDetail bind:offen={detailOffen} id={detailId} ongeaendert={() => { belegeLaden(); laden(); steuerLaden(steuerJahr); }} />
