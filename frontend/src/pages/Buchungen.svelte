<script lang="ts">
  import { ArrowRightLeft, CheckCheck, PenLine, Pencil, Plus, Search, X } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import BuchungDetail from '../components/BuchungDetail.svelte';
  import BuchungNeu from '../components/BuchungNeu.svelte';
  import Header from '../components/Header.svelte';
  import IconKnopf from '../components/IconKnopf.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import KontoBearbeiten from '../components/KontoBearbeiten.svelte';
  import Laden from '../components/Laden.svelte';
  import StandNeu from '../components/StandNeu.svelte';
  import Sheet from '../components/Sheet.svelte';
  import VermoegenChart from '../components/VermoegenChart.svelte';
  import { api } from '../lib/api';
  import { emoji } from '../lib/kategorien';
  import { datumKurz, euro, tagUeberschrift, zeitpunkt } from '../lib/format';
  import { route } from '../lib/router.svelte';
  import { fehler, toast } from '../lib/store.svelte';

  let { konto = null, gruppe = null }: { konto?: number | null; gruppe?: string | null } = $props();

  let info = $state<any>(null);
  let buchungen = $state<any[]>([]);
  let weitere = $state(false);
  let geladen = $state(false);
  let suche = $state('');
  let detailId = $state<number | null>(null);
  let detailOffen = $state(false);
  let neuOffen = $state(false);
  let nameOffen = $state(false);
  let positionen = $state<any[]>([]);
  let bestand = $state<any>(null);
  let position = $state<any>(null);
  let positionOffen = $state(false);

  async function positionZeigen(p: any) {
    position = { ...p, punkte: null };
    positionOffen = true;
    try {
      position = await api(`/accounts/${konto}/positionen/${encodeURIComponent(p.symbol)}`);
    } catch (e) {
      fehler(e);
    }
  }
  let standOffen = $state(route.query.get('stand') === '1');
  let suchTimer: ReturnType<typeof setTimeout> | undefined;
  // Auswahl unter dem Suchfeld: Kategorien und Tags, die in dieser Ansicht vorkommen
  let filterOffen = $state(false);
  let auswahl = $state<{ kategorien: any[]; tags: any[] } | null>(null);
  let katFilter = $state<string | null>(null);
  let tagFilter = $state<string | null>(null);

  function filterZeigen() {
    filterOffen = true;
    if (!auswahl) api(`/buchungen/filter?${new URLSearchParams(filter)}`).then((d) => (auswahl = d)).catch(() => {});
  }

  function filtern(kategorie: string | null, tag: string | null) {
    katFilter = kategorie;
    tagFilter = tag;
    laden(true);
  }

  const filter = $derived<Record<string, string>>(konto !== null ? { konto: String(konto) } : { gruppe: gruppe ?? '' });
  const titel = $derived(info?.name ?? gruppe ?? '');

  async function kopfLaden() {
    const d = await api('/accounts');
    if (konto !== null) {
      for (const g of d.gruppen) for (const k of g.konten) if (k.id === konto) info = k;
    } else {
      const g = d.gruppen.find((x: any) => x.name === gruppe);
      info = { name: gruppe, saldo: g?.summe, ungesehen: g?.ungesehen ?? 0, istGruppe: true };
    }
  }

  async function laden(neu = true) {
    try {
      const params = new URLSearchParams({ ...filter, limit: '60', offset: String(neu ? 0 : buchungen.length) });
      if (suche.trim()) params.set('suche', suche.trim());
      if (katFilter) params.set('kategorie', katFilter);
      if (tagFilter) params.set('tag', tagFilter);
      const d = await api(`/buchungen?${params}`);
      buchungen = neu ? d.buchungen : [...buchungen, ...d.buchungen];
      weitere = d.weitere;
      geladen = true;
    } catch (e) {
      fehler(e);
    }
  }

  // Neue Buchungen bleiben markiert, bis du sie öffnest oder alle als gelesen markierst
  function oeffnen(b: any) {
    detailId = b.id;
    detailOffen = true;
    if (!b.gesehen) {
      b.gesehen = true;
      if (info?.ungesehen) info.ungesehen -= 1;
      api('/buchungen/gesehen', { body: { ids: [b.id] } }).catch(() => {});
    }
  }

  async function alleGelesen() {
    try {
      await api('/buchungen/gesehen', { body: konto !== null ? { konto } : { gruppe } });
      for (const b of buchungen) b.gesehen = true;
      if (info) info.ungesehen = 0;
      toast('Alle als gelesen markiert');
    } catch (e) {
      fehler(e);
    }
  }

  const prozent = (p: number) => `${p > 0 ? '+' : ''}${p.toLocaleString('de-DE', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;

  function suchen() {
    clearTimeout(suchTimer);
    suchTimer = setTimeout(() => laden(true), 300);
  }

  const tage = $derived.by(() => {
    const out: { tag: string; eintraege: any[] }[] = [];
    for (const b of buchungen) {
      if (out.length && out[out.length - 1].tag === b.datum) out[out.length - 1].eintraege.push(b);
      else out.push({ tag: b.datum, eintraege: [b] });
    }
    return out;
  });

  onMount(async () => {
    if (konto !== null) api(`/accounts/${konto}/positionen`).then((d) => { bestand = d; positionen = d.positionen; }).catch(() => {});
    await Promise.all([kopfLaden().catch(fehler), laden(true)]);
  });
</script>

<div class="px-4">
  <Header {titel} gross={false} zurueckZu="#/">
    {#snippet aktionen()}
      {#if konto !== null && info}
        <IconKnopf label="Konto bearbeiten" onclick={() => (nameOffen = true)}><Pencil size={20} /></IconKnopf>
      {/if}
    {/snippet}
  </Header>

  <div class="flex flex-col items-center pb-6 pt-4 text-center">
    <Amount wert={info?.saldo} farbig klasse="text-[36px] font-bold tracking-tight" />
    <div class="mt-1 text-[14px] text-muted">
      {#if info?.istGruppe}Summe aller Konten{:else if info?.stand}Stand: {zeitpunkt(info.stand)}{:else if info}&nbsp;{/if}
      {#if info?.iban_ende} · ••• {info.iban_ende}{/if}
    </div>
    {#if info?.stand_setzbar}
      <div class="mt-4 flex flex-wrap justify-center gap-2">
        {#if info.typ !== 'depot' || info.manuell}
          <button class="pill-accent" onclick={() => (standOffen = true)}><PenLine size={16} /> Stand eintragen</button>
        {/if}
        {#if info.manuell}
          <button class="pill-accent" onclick={() => (neuOffen = true)}><Plus size={16} /> Buchung hinzufügen</button>
        {:else}
          <a class="pill-accent" href="#/konto-neu?csv=1"><Plus size={16} /> {info.typ === 'depot' ? 'Neue Depotübersicht importieren' : 'Weiteren Auszug importieren'}</a>
        {/if}
      </div>
      {#if !info.manuell && info.saldo == null && info.typ !== 'depot'}
        <p class="mt-3 max-w-xs text-[13px] text-muted">
          Der Auszug enthält keinen Kontostand. Trag den aktuellen Stand ein – BankPocket rechnet den Verlauf aus den Buchungen zurück.
        </p>
      {/if}
    {/if}
  </div>

  {#if positionen.length}
    <div class="flex items-baseline justify-between px-1 pb-2 text-[14px] font-semibold text-muted">
      <h3>Bestand ({positionen.length})</h3>
      {#if bestand?.gewinn != null}
        <span class={Number(bestand.gewinn) < 0 ? 'text-neg' : 'text-pos'}>
          <Amount wert={bestand.gewinn} vorzeichen /> · {prozent(bestand.gewinn_prozent)} seit Kauf
        </span>
      {/if}
    </div>
    <div class="karte mb-6 overflow-hidden">
      {#each positionen as p (p.symbol)}
        <button class="zeile" onclick={() => positionZeigen(p)}>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[16px]">{p.name}</span>
            <span class="block truncate text-[13px] text-muted">
              {Number(p.menge).toLocaleString('de-DE', { maximumFractionDigits: 6 })} Stück{#if Number(p.kurs)} · {euro(p.kurs)}{/if}
            </span>
          </span>
          <span class="text-right">
            <Amount wert={p.wert} klasse="block text-[16px] font-medium" />
            {#if p.gewinn != null}
              <span class="block text-[13px] {Number(p.gewinn) < 0 ? 'text-neg' : 'text-pos'}">
                <Amount wert={p.gewinn} vorzeichen /> · {prozent(p.gewinn_prozent)}
              </span>
            {/if}
            {#if p.kurs_prozent != null}
              <span class="block text-[12px] {p.kurs_prozent < 0 ? 'text-neg' : p.kurs_prozent > 0 ? 'text-pos' : 'text-muted'}">
                {prozent(p.kurs_prozent)} seit {datumKurz(bestand.davor)}
              </span>
            {/if}
          </span>
        </button>
      {/each}
    </div>
    <h3 class="px-1 pb-2 text-[14px] font-semibold text-muted">Buchungen</h3>
  {/if}

  <label class="relative mb-2 block">
    <Search size={18} class="absolute left-4 top-1/2 -translate-y-1/2 text-faint" />
    <input
      class="feld !rounded-full !py-3 pl-11"
      placeholder="Suchen oder Kategorie wählen"
      bind:value={suche}
      oninput={suchen}
      onfocus={filterZeigen}
      type="search"
    />
  </label>
  {#if katFilter || tagFilter}
    <div class="mb-2 flex flex-wrap gap-1.5">
      <button class="pill bg-accent text-accent-ink" onclick={() => filtern(null, null)} aria-label="Filter entfernen">
        {katFilter ? `${emoji(katFilter)} ${katFilter}` : `#${tagFilter}`} <X size={14} />
      </button>
    </div>
  {:else if filterOffen && auswahl}
    <div class="-mx-4 mb-2 flex gap-1.5 overflow-x-auto px-4 pb-1">
      {#each auswahl.tags as t (t.name)}
        <button class="pill shrink-0 bg-accent-soft text-accent" onclick={() => filtern(null, t.name)}>#{t.name}</button>
      {/each}
      {#each auswahl.kategorien as k (k.name)}
        <button class="pill shrink-0 border border-line bg-card" onclick={() => filtern(k.name, null)}>
          {emoji(k.name)} {k.name} <span class="text-faint">{k.anzahl}</span>
        </button>
      {/each}
    </div>
  {/if}

  {#if !geladen}
    <Laden form="liste" />
  {:else if !buchungen.length}
    <p class="py-16 text-center text-muted">{suche || katFilter || tagFilter ? 'Nichts gefunden.' : 'Noch keine Buchungen.'}</p>
  {:else}
    {#each tage as t (t.tag)}
      <h3 class="px-1 pb-2 pt-5 text-[14px] font-semibold text-muted">{tagUeberschrift(t.tag)}</h3>
      <div class="karte overflow-hidden">
        {#each t.eintraege as b (b.id)}
          <button class="zeile" onclick={() => oeffnen(b)}>
            <span class="relative">
              <KategorieAvatar kategorie={b.intern ? 'Umbuchung' : b.kategorie} logo={b.logo} groesse={42} rund />
              {#if !b.gesehen}<span class="absolute -right-0.5 -top-0.5 size-3 rounded-full bg-accent ring-2 ring-card"></span>{/if}
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[16px]">{b.gegenpartei || b.buchungstext || 'Buchung'}</span>
              <span class="flex items-center gap-1 truncate text-[13px] text-muted">
                {#if b.intern}<ArrowRightLeft size={12} class="shrink-0" /> Umbuchung{:else}{b.kategorie}{/if}
                {#if b.tags?.length}<span class="shrink-0 text-accent"> · {b.tags.map((t: string) => `#${t}`).join(' ')}</span>{/if}
                {#if info?.istGruppe} · {b.konto_name}{:else if b.verwendungszweck} · {b.verwendungszweck}{/if}
              </span>
            </span>
            <Amount wert={b.betrag} vorzeichen farbig klasse="text-[16px] font-medium {b.intern ? 'opacity-60' : ''}" />
          </button>
        {/each}
      </div>
    {/each}
    {#if weitere}
      <button class="knopf-sekundaer mt-5 w-full" onclick={() => laden(false)}>Ältere Buchungen laden</button>
    {/if}
  {/if}
</div>

{#if info?.ungesehen > 0}
  <button
    class="fixed bottom-24 right-4 z-30 flex items-center gap-2 rounded-full bg-accent px-4 py-3 text-[15px] font-semibold text-accent-ink shadow-lg shadow-black/25 active:scale-[0.97] lg:bottom-8 lg:right-8"
    style="margin-bottom: env(safe-area-inset-bottom)"
    onclick={alleGelesen}
    aria-label="Alle {info.ungesehen} neuen Buchungen als gelesen markieren"
  >
    <CheckCheck size={19} /> Alle gelesen <span class="rounded-full bg-accent-ink/15 px-1.5 text-[13px]">{info.ungesehen}</span>
  </button>
{/if}

<BuchungDetail bind:offen={detailOffen} id={detailId} ongeaendert={() => laden(true)} />
<KontoBearbeiten bind:offen={nameOffen} konto={info} ongespeichert={kopfLaden} />
{#if info?.manuell}
  <BuchungNeu bind:offen={neuOffen} konto={info} ongespeichert={() => { laden(true); kopfLaden(); }} />
{/if}
{#if info?.stand_setzbar}
  <StandNeu bind:offen={standOffen} konto={info} ongespeichert={() => { laden(true); kopfLaden(); }} />
{/if}

<Sheet bind:offen={positionOffen} titel={position?.name ?? ''}>
  {#if position}
    <div class="text-center">
      <Amount wert={position.wert} klasse="text-[32px] font-bold tracking-tight" />
      {#if position.gewinn != null}
        <div class="text-[15px] {Number(position.gewinn) < 0 ? 'text-neg' : 'text-pos'}">
          <Amount wert={position.gewinn} vorzeichen /> · {prozent(position.gewinn_prozent)} seit Kauf
        </div>
      {/if}
      <div class="mt-1 text-[13px] text-muted">
        {Number(position.menge).toLocaleString('de-DE', { maximumFractionDigits: 6 })} Stück · Kurs {euro(position.kurs)}{#if position.einstand} · Kaufkurs Ø {euro(position.einstand)}{/if}
      </div>
    </div>
    {#if !position.punkte}
      <Laden form="liste" />
    {:else if position.punkte.length > 1}
      <div class="karte mt-4 p-4">
        <div class="mb-1 text-[13px] text-muted">Wert deiner Position</div>
        <VermoegenChart punkte={position.punkte.map((p: any) => ({ d: p.d, w: Number(p.w) }))} hoehe={200} />
      </div>
    {:else}
      <p class="karte mt-4 p-4 text-[14px] text-muted">
        Für diese Position gibt es noch keinen Kursverlauf. Er entsteht mit den nächsten Abrufen.
      </p>
    {/if}
    {#if position.kaeufe?.length}
      <h3 class="px-1 pb-2 pt-5 text-[14px] font-semibold text-muted">Käufe und Verkäufe ({position.kaeufe.length})</h3>
      <div class="karte overflow-hidden">
        {#each position.kaeufe.slice(0, 40) as k (k.id)}
          <div class="zeile">
            <span class="min-w-0 flex-1">
              <span class="block text-[15px]">{datumKurz(k.datum)}{String(k.datum).slice(0, 4) !== String(new Date().getFullYear()) ? String(k.datum).slice(0, 4) : ''}</span>
              <span class="block truncate text-[13px] text-muted">{k.text || (Number(k.betrag) < 0 ? 'Kauf' : 'Verkauf')}</span>
            </span>
            <Amount wert={k.betrag} vorzeichen klasse="text-[15px] font-medium" />
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</Sheet>
