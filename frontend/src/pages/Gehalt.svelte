<script lang="ts">
  import { ChevronRight, EyeOff, RotateCcw } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import BuchungDetail from '../components/BuchungDetail.svelte';
  import Header from '../components/Header.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import Laden from '../components/Laden.svelte';
  import Sheet from '../components/Sheet.svelte';
  import { api } from '../lib/api';
  import { datumKurz, euro } from '../lib/format';
  import { fehler, toast } from '../lib/store.svelte';

  const ZEILEN: [string, string, number][] = [['einnahmen', 'Einnahmen', 1], ['vertraege', 'Verträge', -1], ['sparen', 'Sparen', -1], ['sonstige', 'Sonstige Ausgaben', -1]];
  const TITEL: Record<string, string> = { einnahmen: 'Einnahmen', vertraege: 'Verträge', sparen: 'Sparen', sonstige: 'Sonstige Ausgaben', ausgaben: 'Alle Ausgaben', ausgeschlossen: 'Nicht berücksichtigt' };

  let g = $state<any>(null);
  let leer = $state(false);
  let art = $state('sonstige');
  let listeOffen = $state(false);
  let liste = $state<any>(null);
  let detailId = $state<number | null>(null);
  let detailOffen = $state(false);

  async function laden() {
    try {
      g = await api('/gehalt');
    } catch {
      leer = true;
    }
  }

  async function listeLaden() {
    try {
      liste = await api(`/gehalt/buchungen?art=${art}`);
    } catch (e) {
      fehler(e);
    }
  }

  function zeigen(a: string) {
    art = a;
    liste = null;
    listeOffen = true;
    listeLaden();
  }

  // „Nicht berücksichtigen“: Die Buchung bleibt, zählt aber nicht bei „frei verfügbar“ (z. B. Auslagen für andere)
  async function ausschliessen(b: any, wert: boolean) {
    try {
      await api(`/buchungen/${b.id}`, { method: 'PATCH', body: { ausgeschlossen: wert } });
      toast(wert ? 'Wird nicht mehr berücksichtigt' : 'Zählt wieder mit');
      await Promise.all([laden(), listeLaden()]);
    } catch (e) {
      fehler(e);
    }
  }

  const anteilAusgaben = $derived(g && Number(g.detail.einnahmen) > 0 ? Math.min(1, Number(g.ausgaben) / Number(g.detail.einnahmen)) : 1);
  let verlaufWahl = $state<string | null>(null);
  const verlaufMonat = $derived(g?.verlauf.find((v: any) => v.start === verlaufWahl) ?? null);
  const verlaufMax = $derived(Math.max(1, ...(g?.verlauf ?? []).map((v: any) => Math.abs(Number(v.frei)))));
  onMount(laden);
</script>

<div class="px-4">
  <Header titel="Aktueller Monat" zurueckZu="#/" />

  {#if leer}
    <p class="karte p-6 text-center text-[15px] text-muted">Noch kein Gehalt erkannt – bestätige unter Verträge deinen Gehaltseingang.</p>
  {:else if !g}
    <Laden />
  {:else}
    <div class="mb-3 px-1 text-[15px] font-semibold text-accent">{datumKurz(g.start)} – {datumKurz(g.datum)}</div>
    <section class="karte p-5">
      <button class="flex w-full items-center justify-between rounded-xl bg-accent-soft px-4 py-2.5 text-[17px] font-semibold text-pos" onclick={() => zeigen('einnahmen')}>
        <span>Einnahmen</span><Amount wert={g.detail.einnahmen} kurz />
      </button>
      <button class="mt-3 flex items-center justify-between rounded-xl bg-neg-soft px-4 py-2.5 text-[17px] font-semibold text-neg" style="width: {Math.max(52, anteilAusgaben * 100)}%" onclick={() => zeigen('ausgaben')}>
        <span>Ausgaben</span><Amount wert={g.ausgaben} kurz />
      </button>
      <div class="mt-5 border-t border-line pt-4">
        <div class="flex flex-wrap items-baseline gap-x-2.5">
          <Amount wert={g.verfuegbar} kurz klasse="text-[36px] font-bold tracking-tight {Number(g.verfuegbar) < 0 ? 'text-neg' : ''}" />
          <span class="text-[17px]">frei verfügbar</span>
        </div>
        <div class="mt-0.5 text-[15px] text-muted">
          {g.verspaetet ? 'Das Gehalt ist noch nicht da' : g.tage === 0 ? 'Gehalt heute erwartet' : `bis zum nächsten Gehalt in ${g.tage} ${g.tage === 1 ? 'Tag' : 'Tagen'}`}
        </div>
      </div>
    </section>

    <h2 class="abschnitt">Im Detail</h2>
    <div class="karte divide-y divide-line overflow-hidden text-[16px]">
      {#each ZEILEN as [schluessel, label, vz] (schluessel)}
        <button class="flex w-full items-center justify-between gap-3 px-4 py-4 text-left active:bg-card-hi" onclick={() => zeigen(schluessel)}>
          <span class="min-w-0">
            {label}
            {#if Number(g.offen[schluessel] ?? 0) > 0}
              <span class="block text-[13px] text-muted">davon {euro(g.offen[schluessel])} noch erwartet</span>
            {/if}
          </span>
          <span class="flex shrink-0 items-center gap-1.5">
            <Amount wert={vz * Number(g.detail[schluessel])} klasse={vz > 0 ? 'text-pos' : ''} />
            <ChevronRight size={18} class="text-faint" />
          </span>
        </button>
      {/each}
      <div class="border-t-2 !border-line px-4 py-4">
        <div class="flex items-center justify-between font-bold">
          <span>Frei verfügbar</span>
          <Amount wert={g.verfuegbar} klasse={Number(g.verfuegbar) < 0 ? 'text-neg' : 'text-pos'} />
        </div>
        {#if g.pro_tag}
          <div class="mt-2 flex justify-end"><span class="pill bg-accent-soft text-pos">Ø {euro(g.pro_tag)} / Tag</span></div>
        {/if}
      </div>
    </div>

    {#if g.prognose !== null}
      <p class="mt-3 px-1 text-[13px] leading-relaxed text-muted">
        Im üblichen Tempo ({euro(g.tempo_pro_tag)} am Tag für Alltägliches, Schnitt der letzten drei Monate) bleiben am {datumKurz(g.datum)} etwa
        <b class="font-semibold {Number(g.prognose) < 0 ? 'text-neg' : 'text-pos'}">{euro(g.prognose, { vorzeichen: true, kurz: true })}</b>.
        {#if g.rhythmus}Dein Gehalt kommt {g.rhythmus}.{/if}
      </p>
    {/if}

    {#if g.ausgeschlossen}
      <button class="karte mt-4 w-full px-5 py-4 text-left text-[16px] font-medium text-accent active:bg-card-hi" onclick={() => zeigen('ausgeschlossen')}>
        {g.ausgeschlossen} {g.ausgeschlossen === 1 ? 'Buchung' : 'Buchungen'} nicht berücksichtigt
      </button>
    {/if}

    {#if g.verlauf.length}
      <h2 class="abschnitt">Dein Verlauf</h2>
      <div class="karte p-5">
        <div class="flex h-36 items-stretch gap-2">
          {#each g.verlauf as v (v.start)}
            {@const hoehe = Math.max(4, (Math.abs(Number(v.frei)) / verlaufMax) * 100)}
            <button class="flex flex-1 flex-col rounded-lg text-center {verlaufWahl === v.start ? 'bg-card-hi' : ''}" onclick={() => (verlaufWahl = verlaufWahl === v.start ? null : v.start)}>
              <span class="flex flex-1 items-end justify-center">
                {#if Number(v.frei) >= 0}<span class="w-4 rounded-full bg-pos" style="height: {hoehe}%"></span>{/if}
              </span>
              <span class="h-px bg-line"></span>
              <span class="flex flex-1 items-start justify-center">
                {#if Number(v.frei) < 0}<span class="w-4 rounded-full bg-neg" style="height: {hoehe}%"></span>{/if}
              </span>
              <span class="mt-1 text-[11px] font-semibold {Number(v.frei) < 0 ? 'text-neg' : 'text-pos'}">{euro(v.frei, { kurz: true })}</span>
              <span class="text-[10px] text-muted">ab {datumKurz(v.start)}</span>
            </button>
          {/each}
        </div>
        {#if verlaufMonat}
          <p class="mt-3 text-center text-[13px] text-muted">
            <b class="font-semibold text-text">{datumKurz(verlaufMonat.start)} – {datumKurz(verlaufMonat.ende)}</b>: {euro(verlaufMonat.einnahmen, { kurz: true })} Einnahmen, {euro(verlaufMonat.ausgaben, { kurz: true })} Ausgaben
          </p>
        {:else}
          <p class="mt-3 text-[12px] text-faint">Was in den Gehaltsmonaten davor am Ende übrig blieb (Einnahmen minus alle Ausgaben) – antippen für die Zahlen.</p>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<Sheet bind:offen={listeOffen} titel={TITEL[art]}>
  {#if !liste}
    <Laden form="liste" />
  {:else}
    {#if liste.offen.length}
      <div class="label">Noch erwartet bis {datumKurz(g.datum)}</div>
      <div class="karte mb-4 overflow-hidden">
        {#each liste.offen as p (p.id + p.datum)}
          <a class="zeile" href="#/vertrag/{p.id}">
            <KategorieAvatar kategorie={p.kategorie} groesse={40} />
            <span class="min-w-0 flex-1"><span class="block truncate text-[16px]">{p.name}</span><span class="block text-[13px] text-muted">{datumKurz(p.datum)}</span></span>
            <Amount wert={art === 'einnahmen' ? p.betrag : -p.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
          </a>
        {/each}
      </div>
      <div class="label">Schon gebucht</div>
    {/if}
    {#if liste.buchungen.length}
      <div class="karte overflow-hidden">
        {#each liste.buchungen as b (b.id)}
          <div class="flex items-center">
            <button class="zeile min-w-0 flex-1 !pr-1" onclick={() => { detailId = b.id; detailOffen = true; }}>
              <KategorieAvatar kategorie={b.kategorie} logo={b.logo} groesse={40} rund />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-[16px]">{b.gegenpartei || b.verwendungszweck || b.buchungstext || 'Buchung'}</span>
                <span class="block truncate text-[13px] text-muted">{datumKurz(b.datum)} · {b.mein_betrag ? `dein Anteil ${euro(Math.abs(Number(b.mein_betrag)))}` : b.konto_name}</span>
              </span>
              <Amount wert={b.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
            </button>
            <button
              class="grid size-11 shrink-0 place-items-center text-muted active:text-accent"
              onclick={() => ausschliessen(b, art !== 'ausgeschlossen')}
              aria-label={art === 'ausgeschlossen' ? 'Wieder berücksichtigen' : 'Nicht berücksichtigen'}
            >
              {#if art === 'ausgeschlossen'}<RotateCcw size={18} />{:else}<EyeOff size={18} />{/if}
            </button>
          </div>
        {/each}
      </div>
      <p class="mt-3 text-[13px] text-muted">
        {art === 'ausgeschlossen' ? 'Der Pfeil nimmt eine Buchung wieder in die Rechnung auf.' : 'Das durchgestrichene Auge nimmt eine Buchung aus der Rechnung – etwa Auslagen, die du zurückbekommst.'}
      </p>
    {:else if !liste.offen.length}
      <p class="py-8 text-center text-[15px] text-muted">Keine Buchungen.</p>
    {/if}
  {/if}
</Sheet>
<BuchungDetail bind:offen={detailOffen} id={detailId} ongeaendert={() => { laden(); listeLaden(); }} />
