<script lang="ts">
  import { Bell, ChevronDown, ChevronRight, Eye, EyeOff, Inbox, Landmark, Layers, PenLine, Plus, RefreshCw, Settings, TriangleAlert } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import { slide } from 'svelte/transition';
  import AbrufStatus from '../components/AbrufStatus.svelte';
  import Amount from '../components/Amount.svelte';
  import Badge from '../components/Badge.svelte';
  import BankAvatar from '../components/BankAvatar.svelte';
  import BuchungNeu from '../components/BuchungNeu.svelte';
  import StandNeu from '../components/StandNeu.svelte';
  import BudgetRing from '../components/BudgetRing.svelte';
  import Header from '../components/Header.svelte';
  import IconKnopf from '../components/IconKnopf.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import Laden from '../components/Laden.svelte';
  import Sheet from '../components/Sheet.svelte';
  import Startbildschirm from '../components/Startbildschirm.svelte';
  import VermoegenChart from '../components/VermoegenChart.svelte';
  import { api } from '../lib/api';
  import { datumKurz, monatName, zeitpunkt } from '../lib/format';
  import { gehe } from '../lib/router.svelte';
  import { fehler, merker, toast, ui, versteckenUmschalten } from '../lib/store.svelte';

  let daten = $state<any>(null);
  let zu = $state<Record<string, boolean>>(JSON.parse(merker.lesen('bp_zu') ?? '{}'));
  // Ausgeblendete Konten (zählen nicht zur Summe) erscheinen erst nach einem Tipp auf den Link ganz unten
  let alleZeigen = $state(false);
  const sichtbar = (g: any) => (alleZeigen ? g.konten : g.konten.filter((k: any) => k.aktiv));
  const ausgeblendet = $derived((daten?.gruppen ?? []).reduce((n: number, g: any) => n + g.konten.filter((k: any) => !k.aktiv).length, 0));
  let laeuft = $state(false);
  let aktiveFreigabe = $state<any>(null);
  let sheetOffen = $state(false);
  let buchungKonto = $state<{ id: number; name: string; saldo?: number | null } | null>(null);
  let buchungOffen = $state(false);
  let standOffen = $state(false);
  let timer: ReturnType<typeof setInterval> | undefined;

  // Am PC wird die Übersicht zum Dashboard: Kennzahlen, Vermögensverlauf und die nächsten Zahlungen kommen dazu
  const breitMedia = window.matchMedia('(min-width: 1024px)');
  let breit = $state(breitMedia.matches);
  let kennzahlen = $state<any>(null);

  async function kennzahlenLaden() {
    if (!breit) return;
    try {
      const [vermoegen, monat, vertraege, kalender] = await Promise.all([
        api('/analysen/vermoegen?tage=30'), api('/analysen/monat'), api('/contracts'), api('/kalender?tage=21'),
      ]);
      const termine = kalender.tage.flatMap((t: any) => t.eintraege).slice(0, 6);
      kennzahlen = { vermoegen, monat, vertraege, termine, vormonat: monat.verlauf.at(-2) };
    } catch {
      kennzahlen = null; // das Dashboard ist Beiwerk – die Übersicht funktioniert auch ohne
    }
  }

  async function laden() {
    try {
      daten = await api('/uebersicht');
      kennzahlenLaden();
      if (daten.verbindungen.some((v: any) => v.laeuft) && !timer) beobachten();
    } catch (e) {
      fehler(e);
    }
  }

  async function aktualisieren() {
    if (laeuft) return;
    try {
      const r = await api('/aktualisieren', { method: 'POST' });
      if (!r.gestartet.length) {
        toast(daten?.verbindungen.length ? 'Bitte zuerst die markierten Verbindungen prüfen.' : 'Verbinde zuerst eine Bank.');
        return;
      }
      beobachten();
    } catch (e) {
      fehler(e);
    }
  }

  function beobachten() {
    laeuft = true;
    clearInterval(timer);
    timer = setInterval(async () => {
      try {
        const vs = await api('/verbindungen');
        const aktiv = vs.filter((v: any) => v.live?.laeuft);
        const wartet = aktiv.find((v: any) => ['freigabe', 'tan', 'auswahl'].includes(v.live.phase));
        aktiveFreigabe = wartet ?? null;
        sheetOffen = !!wartet;
        if (!aktiv.length) {
          clearInterval(timer);
          timer = undefined;
          laeuft = false;
          await laden();
          const fehlgeschlagen = vs.filter((v: any) => v.live?.phase === 'fehler');
          if (fehlgeschlagen.length) toast(`${fehlgeschlagen[0].name}: ${fehlgeschlagen[0].live.text}`, 'fehler');
          else toast('Alles aktuell');
        }
      } catch (e) {
        clearInterval(timer);
        timer = undefined;
        laeuft = false;
      }
    }, 1200);
  }

  function umschalten(name: string) {
    zu[name] = !zu[name];
    merker.schreiben('bp_zu', JSON.stringify(zu));
  }

  function veraltet(k: any) {
    return k.stand && Date.now() - new Date(k.stand).getTime() > 6 * 3600 * 1000;
  }

  onMount(() => {
    laden();
    const wechsel = () => {
      breit = breitMedia.matches;
      kennzahlenLaden();
    };
    breitMedia.addEventListener('change', wechsel);
    return () => {
      clearInterval(timer);
      breitMedia.removeEventListener('change', wechsel);
    };
  });
</script>

<div class="px-4">
  <Header titel="Übersicht">
    {#snippet aktionen()}
      <IconKnopf label={ui.versteckt ? 'Beträge anzeigen' : 'Beträge ausblenden'} onclick={versteckenUmschalten}>
        {#if ui.versteckt}<EyeOff size={22} />{:else}<Eye size={22} />{/if}
      </IconKnopf>
      <IconKnopf label="Hinweise" href="#/hinweise" badge={daten?.hinweise_ungelesen ?? 0}><Bell size={22} /></IconKnopf>
      <IconKnopf label="Einstellungen" href="#/einstellungen"><Settings size={22} /></IconKnopf>
    {/snippet}
  </Header>

  {#if !daten}
    <Laden />
  {:else}
    {#each daten.banner as b (b.link + b.art)}
      <a
        href={b.link}
        class="mb-3 flex items-center gap-3 rounded-2xl px-4 py-3.5 {b.art === 'freigabe_noetig' || b.art === 'auswahl_noetig'
          ? 'bg-warn-soft text-warn'
          : 'bg-neg-soft text-neg'}"
      >
        <TriangleAlert size={20} class="shrink-0" />
        <span class="flex-1 text-[14px] leading-snug"><b class="font-semibold">{b.titel}</b> · {b.text}</span>
        <ChevronRight size={18} class="shrink-0" />
      </a>
    {/each}

    {#if breit && kennzahlen}
      {@const k = kennzahlen}
      <div class="mb-6 grid grid-cols-4 gap-4">
        <a href="#/analysen" class="karte block p-5">
          <div class="text-[13px] font-semibold text-muted">Vermögen</div>
          <Amount wert={daten.gesamtsumme} klasse="mt-2 block text-[26px] font-bold tracking-tight" />
          <div class="mt-1 text-[13px] {Number(k.vermoegen.veraenderung) < 0 ? 'text-neg' : 'text-pos'}">
            <Amount wert={k.vermoegen.veraenderung} vorzeichen /> in 30 Tagen
          </div>
        </a>
        <a href="#/analysen" class="karte block p-5">
          <div class="text-[13px] font-semibold text-muted">Ausgaben im {monatName(k.monat.monat).split(' ')[0]}</div>
          <Amount wert={k.monat.ausgaben} klasse="mt-2 block text-[26px] font-bold tracking-tight" />
          <div class="mt-1 text-[13px] text-muted">{#if k.vormonat}Vormonat <Amount wert={k.vormonat.ausgaben} />{:else}&nbsp;{/if}</div>
        </a>
        <a href="#/analysen" class="karte block p-5">
          <div class="text-[13px] font-semibold text-muted">Einnahmen im {monatName(k.monat.monat).split(' ')[0]}</div>
          <Amount wert={k.monat.einnahmen} klasse="mt-2 block text-[26px] font-bold tracking-tight" />
          <div class="mt-1 text-[13px] text-muted">{#if k.vormonat}Vormonat <Amount wert={k.vormonat.einnahmen} />{:else}&nbsp;{/if}</div>
        </a>
        <a href="#/vertraege" class="karte block p-5">
          <div class="text-[13px] font-semibold text-muted">Verträge pro Monat</div>
          <Amount
            wert={Number(k.vertraege.ausgaben_monatlich) + Number(k.vertraege.sparen_monatlich)}
            klasse="mt-2 block text-[26px] font-bold tracking-tight"
          />
          <div class="mt-1 text-[13px] text-muted">
            {#if k.vertraege.vorschlaege.length}<span class="text-warn">{k.vertraege.vorschlaege.length} zu bestätigen</span>
            {:else if Number(k.vertraege.sparen_monatlich) > 0}davon <Amount wert={k.vertraege.sparen_monatlich} /> Sparpläne
            {:else}&nbsp;{/if}
          </div>
        </a>
      </div>
    {/if}

    <!-- Am PC: Konten links, Gehalt und Budgets rechts. Auf dem Handy untereinander wie gehabt. -->
    <div class="lg:grid lg:grid-cols-2 lg:items-start lg:gap-x-8">
    <div class="lg:order-2">
    {#if daten.gehalt}
      {@const g = daten.gehalt}
      <a class="karte block w-full p-5 text-left" href="#/gehalt">
        <div class="flex items-center justify-between text-[15px]">
          <span class="font-semibold">Gehalt</span>
          <span class="flex items-center gap-1 {g.verspaetet ? 'text-warn' : 'text-muted'}">
            {g.verspaetet ? 'Gehalt noch nicht da' : g.tage === 0 ? 'Gehalt heute erwartet' : `${g.tage} ${g.tage === 1 ? 'Tag' : 'Tage'} bis zum Gehalt`}
            <ChevronRight size={18} />
          </span>
        </div>
        <div class="mt-4 flex flex-wrap items-baseline gap-x-2.5">
          <Amount wert={g.verfuegbar} klasse="text-[30px] font-bold tracking-tight" />
          <span class="text-[15px] text-muted">frei verfügbar</span>
        </div>
        <div class="mt-4 h-2 overflow-hidden rounded-full bg-spur">
          <div class="h-full rounded-full bg-accent transition-[width] duration-700" style="width: {Math.round(g.anteil * 100)}%"></div>
        </div>
        {#if g.pro_tag || g.prognose !== null}
          <div class="mt-4 grid grid-cols-2 gap-3">
            {#if g.pro_tag}
              <div class="rounded-2xl bg-card-hi px-3.5 py-3">
                <div class="text-[13px] text-muted">pro Tag</div>
                <div class="mt-0.5 text-[17px] font-semibold"><Amount wert={g.pro_tag} /></div>
              </div>
            {/if}
            {#if g.prognose !== null}
              <div class="rounded-2xl bg-card-hi px-3.5 py-3">
                <div class="text-[13px] text-muted">übrig am {datumKurz(g.datum)}</div>
                <div class="mt-0.5 text-[17px] font-semibold {Number(g.prognose) < 0 ? 'text-neg' : 'text-pos'}">≈ <Amount wert={g.prognose} vorzeichen /></div>
              </div>
            {/if}
          </div>
        {/if}
        {#if Number(g.ausstehend) > 0}
          <p class="mt-3 text-[13px] text-muted">
            Nach Abzug von <Amount wert={g.ausstehend} /> Fixkosten bis {datumKurz(g.datum)}
          </p>
        {/if}
      </a>
    {:else if !daten.verbindungen.length}
      <a href="#/verbinden" class="karte block p-5">
        <div class="flex items-center gap-4">
          <span class="grid size-12 shrink-0 place-items-center rounded-2xl bg-accent-soft text-accent"><Landmark size={24} /></span>
          <div class="flex-1">
            <div class="text-[17px] font-semibold">Bank verbinden</div>
            <div class="mt-0.5 text-[14px] text-muted">ING, Consorsbank & Co. – Umsätze kommen dann automatisch.</div>
          </div>
          <ChevronRight size={20} class="text-accent" />
        </div>
      </a>
    {/if}

    {#if (daten.verbindungen.length || daten.budgets.length) && !ui.budgetsAus}
      <div class="karte mt-3 p-5">
        <div class="flex items-center justify-between">
          <span class="text-[17px] font-semibold">Budgets</span>
          <a href="#/budgets" class="flex items-center gap-0.5 text-[15px] font-medium text-accent">
            {daten.budgets.length ? 'Alle anzeigen' : 'Einrichten'}<ChevronRight size={18} />
          </a>
        </div>
        <div class="-mx-1 mt-4 flex gap-3 overflow-x-auto px-1 pb-1">
          {#each daten.budgets as b (b.id)}
            <a href="#/budgets" aria-label="Budget {b.kategorie}"><BudgetRing kategorie={b.kategorie} anteil={b.anteil} status={b.status} /></a>
          {/each}
          <a href="#/budgets?neu=1" class="grid size-[58px] shrink-0 place-items-center rounded-full bg-card-hi text-accent" aria-label="Budget anlegen">
            <Plus size={26} />
          </a>
        </div>
      </div>
    {/if}

    {#if breit && kennzahlen}
      {#if kennzahlen.vermoegen.punkte.length > 1}
        <a href="#/analysen" class="karte mt-3 block p-5">
          <div class="flex items-center justify-between">
            <span class="text-[17px] font-semibold">Vermögen · 30 Tage</span>
            <span class="flex items-center gap-0.5 text-[15px] font-medium text-accent">Analysen<ChevronRight size={18} /></span>
          </div>
          <div class="mt-2"><VermoegenChart punkte={kennzahlen.vermoegen.punkte} hoehe={170} /></div>
        </a>
      {/if}
      {#if kennzahlen.termine.length}
        <div class="karte mt-3 overflow-hidden">
          <a href="#/kalender" class="flex items-center justify-between px-5 pb-2 pt-5">
            <span class="text-[17px] font-semibold">Nächste Zahlungen</span>
            <span class="flex items-center gap-0.5 text-[15px] font-medium text-accent">Kalender<ChevronRight size={18} /></span>
          </a>
          {#each kennzahlen.termine as t (t.id + t.datum)}
            <a class="zeile" href="#/vertrag/{t.id}">
              <KategorieAvatar kategorie={t.kategorie} groesse={36} />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-[15px]">{t.name}</span>
                <span class="text-[13px] {t.ueberfaellig ? 'text-warn' : 'text-muted'}">{t.ueberfaellig ? 'überfällig seit ' : ''}{datumKurz(t.datum)}</span>
              </span>
              <Amount wert={t.betrag} vorzeichen farbig klasse="text-[15px] font-medium" />
            </a>
          {/each}
        </div>
      {/if}
    {/if}
    </div>
    <div class="lg:order-1 lg:-mt-7">
    {#each daten.gruppen.filter((g: any) => sichtbar(g).length) as g (g.name)}
      <section>
        <button class="abschnitt flex w-full items-center justify-between" onclick={() => umschalten(g.name)} aria-expanded={!zu[g.name]}>
          <span>{g.name}</span>
          <span class="flex items-center gap-2">
            {#if zu[g.name]}<Amount wert={g.summe} farbig klasse="text-[17px] font-medium" />{/if}
            <ChevronDown size={24} class="text-accent transition-transform duration-200 {zu[g.name] ? '-rotate-90' : ''}" />
          </span>
        </button>
        {#if !zu[g.name]}
          <div class="karte overflow-hidden" transition:slide={{ duration: 200 }}>
            <a class="zeile" href="#/gruppe/{encodeURIComponent(g.name)}">
              <span class="relative grid size-11 shrink-0 place-items-center rounded-[14px] bg-card-hi text-text">
                <Inbox size={22} />
                {#if g.ungesehen}<Badge n={g.ungesehen} />{/if}
              </span>
              <span class="flex-1 text-[17px]">Alle Buchungen</span>
              <Amount wert={g.summe} farbig klasse="text-[17px] font-medium" />
            </a>
            {#each sichtbar(g) as k (k.id)}
              <div
                class="zeile cursor-pointer"
                role="link"
                tabindex="0"
                onclick={() => gehe(`/konto/${k.id}`)}
                onkeydown={(e) => e.key === 'Enter' && gehe(`/konto/${k.id}`)}
              >
                <span class="relative">
                  <BankAvatar quelle={k.quelle} name={k.name} />
                  {#if k.ungesehen && k.aktiv}<Badge n={k.ungesehen} />{/if}
                </span>
                <div class="min-w-0 flex-1">
                  <div class="truncate text-[17px] {k.aktiv ? '' : 'text-muted'}">{k.name}</div>
                  {#if k.stand}
                    <div class="truncate text-[12px] {!k.manuell && veraltet(k) ? 'text-warn' : 'text-faint'}">Stand: {zeitpunkt(k.stand)}</div>
                  {/if}
                  {#if k.manuell && k.aktiv && k.typ === 'virtuell'}
                    <button
                      class="pill-accent mt-2 !px-2.5 !py-1 text-[13px]"
                      onclick={(e) => { e.stopPropagation(); buchungKonto = k; standOffen = true; }}
                    >
                      <PenLine size={16} /> Stand eintragen
                    </button>
                  {:else if k.manuell && k.aktiv}
                    <button
                      class="pill-accent mt-2 !px-2.5 !py-1 text-[13px]"
                      onclick={(e) => { e.stopPropagation(); buchungKonto = k; buchungOffen = true; }}
                    >
                      <Plus size={16} /> Buchung hinzufügen
                    </button>
                  {:else if ['freigabe_noetig', 'pin_falsch', 'gesperrt', 'auswahl_noetig'].includes(k.verbindung_status)}
                    <span class="mt-1.5 inline-flex items-center gap-1.5 rounded-lg bg-warn-soft px-2 py-1 text-[12px] text-warn">
                      <TriangleAlert size={12} /> Abruf pausiert
                    </span>
                  {/if}
                </div>
                {#if !k.aktiv}
                  <span class="rounded-lg bg-card-hi px-2.5 py-1 text-[14px] text-muted">Ausgeblendet</span>
                {:else}
                  <Amount wert={k.saldo} farbig klasse="text-[17px] font-medium" />
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </section>
    {/each}

    {#if daten.gruppen.some((g: any) => g.konten.length)}
      <div class="karte mt-7 overflow-hidden">
        <div class="zeile">
          <span class="grid size-11 shrink-0 place-items-center rounded-[14px] bg-card-hi text-text"><Layers size={22} /></span>
          <span class="flex-1 text-[17px] font-semibold">Gesamtsumme</span>
          <Amount wert={daten.gesamtsumme} farbig klasse="text-[17px] font-semibold" />
        </div>
      </div>
    {/if}
    {#if ausgeblendet}
      <button class="mt-4 w-full px-1 text-center text-[14px] font-medium text-accent" onclick={() => (alleZeigen = !alleZeigen)}>
        {alleZeigen ? 'Ausgeblendete Konten verbergen' : `${ausgeblendet} ausgeblendete${ausgeblendet === 1 ? 's Konto' : ' Konten'} anzeigen`}
      </button>
    {/if}

    </div>
    </div>

    <div class="mt-7 flex flex-col items-center gap-3">
      <a href="#/konto-neu" class="pill-accent !rounded-2xl !px-5 !py-3 text-[16px] font-semibold"><Plus size={20} /> Konto hinzufügen</a>
    </div>
    <Startbildschirm hinweis />

    <button class="mx-auto mt-6 flex items-center gap-2 py-2 text-[15px] text-muted" onclick={aktualisieren} disabled={laeuft}>
      <RefreshCw size={17} class={laeuft ? 'animate-spin text-accent' : ''} />
      {#if laeuft}Aktualisiere …{:else}{zeitpunkt(daten.letzte_aktualisierung)} <span class="text-faint">|</span>
        <b class="font-semibold text-text">Aktualisieren</b>{/if}
    </button>
  {/if}
</div>

<Sheet bind:offen={sheetOffen}>
  {#if aktiveFreigabe}<AbrufStatus v={aktiveFreigabe} />{/if}
</Sheet>

<BuchungNeu bind:offen={buchungOffen} konto={buchungKonto} ongespeichert={laden} />
<StandNeu bind:offen={standOffen} konto={buchungKonto} ongespeichert={laden} />
