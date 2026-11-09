<script lang="ts">
  import { ArrowRightLeft, ChevronRight, EyeOff, Receipt, Sparkles, Undo2, X } from '@lucide/svelte';
  import { api } from '../lib/api';
  import { datum, euro, TURNUS } from '../lib/format';
  import { kategorieNeu, kategorienLaden } from '../lib/kategorieNeu';
  import { emoji } from '../lib/kategorien';
  import { fehler, toast } from '../lib/store.svelte';
  import Amount from './Amount.svelte';
  import DatumFeld from './DatumFeld.svelte';
  import KategorieAvatar from './KategorieAvatar.svelte';
  import Auswahl from './Auswahl.svelte';
  import KategorieWahl from './KategorieWahl.svelte';
  import Laden from './Laden.svelte';
  import Sheet from './Sheet.svelte';

  let { offen = $bindable(false), id, ongeaendert }: { offen: boolean; id: number | null; ongeaendert?: () => void } = $props();

  let b = $state<any>(null);
  let kategorien = $state<{ ausgabe: string[]; einnahme: string[] } | null>(null);
  let merkenVorschlag = $state<string | null>(null);
  let vertraege = $state<any[] | null>(null);
  let vertragWahl = $state('');
  let neuerTurnus = $state('monatlich');
  let notiz = $state('');
  let tagEingabe = $state('');
  let erkennt = $state(false);
  let gegenKandidaten = $state<any[] | null>(null);

  async function gegenSuchen() {
    try {
      gegenKandidaten = await api(`/buchungen/${b.id}/gegenbuchungen`);
    } catch (e) {
      fehler(e);
    }
  }

  async function gegenWaehlen(k: any) {
    try {
      b = { ...b, ...(await api('/umbuchungen', { body: { a: b.id, b: k.id } })) };
      gegenKandidaten = null;
      toast('Gegenbuchung verbunden');
      ongeaendert?.();
    } catch (e) {
      fehler(e);
    }
  }

  async function gegenLoesen() {
    try {
      await api(`/umbuchungen/${b.id}`, { method: 'DELETE' });
      b = { ...b, gegenbuchung: null, gegenbuchung_id: null };
      toast('Gegenbuchung gelöst');
      ongeaendert?.();
    } catch (e) {
      fehler(e);
    }
  }

  async function erkennen() {
    erkennt = true;
    try {
      const r = await api(`/buchungen/${b.id}/erkennen`, { method: 'POST' });
      b = { ...b, ...r };
      toast(r.erkannt ? `Erkannt: ${r.erkannt}` : 'Die KI konnte diese Buchung nicht einordnen.', r.erkannt ? 'ok' : 'fehler');
      if (r.erkannt) ongeaendert?.();
    } catch (e) {
      fehler(e);
    } finally {
      erkennt = false;
    }
  }
  let eDatum = $state('');
  let eText = $state('');
  let eBetrag = $state('');
  let alleTags = $state<{ tag: string; anzahl: number }[]>([]);
  const HERKUNFT: Record<string, string> = {
    manuell: 'Von dir gewählt',
    regel: 'Automatisch erkannt',
    ki: 'Von der KI eingeordnet',
    standard: 'Nicht erkannt – wähle eine Kategorie, BankPocket merkt sie sich',
  };

  $effect(() => {
    if (offen && id) {
      b = null;
      merkenVorschlag = null;
      vertragWahl = '';
      gegenKandidaten = null;
      tagEingabe = '';
      api('/tags').then((t) => (alleTags = t)).catch(() => {});
      api(`/buchungen/${id}`).then((d) => { b = d; notiz = d.notiz; felderFuellen(); }).catch(fehler);
      if (!kategorien) kategorienLaden().then((k) => (kategorien = k));
    }
  });

  async function merken() {
    try {
      const r = await api('/regeln', {
        body: { stichwort: b.haendler, kategorie: merkenVorschlag, typ: b.betrag > 0 ? 'einnahme' : 'ausgabe' },
      });
      toast(`Gemerkt – ${r.geaendert} ${r.geaendert === 1 ? 'Buchung' : 'Buchungen'} eingeordnet`);
      merkenVorschlag = null;
      ongeaendert?.();
    } catch (e) {
      fehler(e);
    }
  }

  async function aendern(felder: Record<string, unknown>, meldung?: string) {
    try {
      b = { ...b, ...(await api(`/buchungen/${b.id}`, { method: 'PATCH', body: felder })) };
      if (meldung) toast(meldung);
      ongeaendert?.();
    } catch (e) {
      fehler(e);
    }
  }

  // Selbst eingetragene Buchungen: Datum, Text und Betrag lassen sich nachträglich ändern
  function felderFuellen() {
    eDatum = b.datum;
    eText = b.gegenpartei;
    eBetrag = Math.abs(Number(b.betrag)).toFixed(2).replace('.', ',');
  }

  async function eigeneSpeichern(e: SubmitEvent) {
    e.preventDefault();
    const zahl = Number(eBetrag.replace(/\./g, '').replace(',', '.'));
    if (!(zahl > 0) || !eDatum) return;
    await aendern({ datum: eDatum, gegenpartei: eText, betrag: (Number(b.betrag) < 0 ? -zahl : zahl).toFixed(2) }, 'Buchung geändert');
    felderFuellen();
  }

  async function eigeneLoeschen() {
    if (!confirm('Diese Buchung löschen?')) return;
    try {
      await api(`/buchungen/${b.id}`, { method: 'DELETE' });
      toast('Buchung gelöscht');
      offen = false;
      ongeaendert?.();
    } catch (e) {
      fehler(e);
    }
  }

  // Kategorie, die es noch nicht gibt: anlegen und der Buchung gleich geben
  async function kategorieAnlegen(name: string) {
    try {
      kategorien = await kategorieNeu(name, b.betrag > 0 && !b.rueckzahlung ? 'einnahme' : 'ausgabe');
      await kategorieSetzen(name);
      toast(`Kategorie „${name}“ angelegt – das Emoji änderst du unter Kategorien & Regeln`);
    } catch (err) {
      fehler(err);
    }
  }

  async function tagDazu(tag: string) {
    const neu = tag.trim().replace(/^#/, '');
    tagEingabe = '';
    if (neu && !b.tags.some((t: string) => t.toLowerCase() === neu.toLowerCase())) await aendern({ tags: [...b.tags, neu] });
  }

  const tagVorschlaege = $derived(
    alleTags
      .map((t) => t.tag)
      .filter((t) => !b?.tags.includes(t) && t.toLowerCase().includes(tagEingabe.trim().replace(/^#/, '').toLowerCase()))
      .slice(0, 6),
  );

  async function vertraegeLaden() {
    if (vertraege) return;
    try {
      const d = await api('/contracts');
      vertraege = [...d.ausgaben, ...d.einnahmen].flatMap((s: any) => s.vertraege).concat(d.vorschlaege)
        .filter((c: any) => (c.typ === 'einnahme') === b.betrag > 0)
        .sort((x: any, y: any) => x.name.localeCompare(y.name));
    } catch (e) {
      fehler(e);
    }
  }

  async function vertragZuordnen() {
    if (vertragWahl === 'neu') {
      try {
        b = { ...b, ...(await api(`/buchungen/${b.id}/vertrag`, { body: { turnus: neuerTurnus } })) };
        toast('Vertrag angelegt');
        vertraege = null;
        ongeaendert?.();
      } catch (e) {
        fehler(e);
      }
    } else if (vertragWahl) await aendern({ contract_id: Number(vertragWahl) }, 'Vertrag zugeordnet');
    vertragWahl = '';
  }

  async function kategorieSetzen(k: string) {
    try {
      b = { ...b, ...(await api(`/buchungen/${b.id}`, { method: 'PATCH', body: { kategorie: k } })) };
      merkenVorschlag = b.haendler ? k : null;
      ongeaendert?.();
    } catch (e) {
      fehler(e);
    }
  }
</script>

<Sheet bind:offen>
  {#if b}
    <div class="flex flex-col items-center pb-2 text-center">
      <KategorieAvatar kategorie={b.intern ? 'Umbuchung' : b.kategorie} logo={b.logo} groesse={60} rund />
      <div class="mt-3 text-[17px] font-semibold">{b.gegenpartei || b.buchungstext || 'Buchung'}</div>
      <Amount wert={b.betrag} vorzeichen farbig klasse="mt-1 text-[34px] font-bold tracking-tight" />
      <div class="mt-1 text-[14px] text-muted">{datum(b.datum)} · {b.konto_name}</div>
      {#if b.rueckzahlung}
        <span class="pill mt-3 bg-accent-soft text-accent"><Undo2 size={14} /> Rückzahlung · mindert {b.kategorie}</span>
      {/if}
      {#if b.mein_betrag}
        <span class="pill mt-3 bg-accent-soft text-accent">Dein Anteil {b.vertrag?.anteil_prozent} % · {euro(Math.abs(Number(b.mein_betrag)))}</span>
      {/if}
      {#if b.intern}
        <span class="pill mt-3 bg-card-hi text-muted"><ArrowRightLeft size={14} /> Umbuchung zwischen deinen Konten</span>
      {/if}
      {#if b.notiz}<p class="mt-2 max-w-xs text-[14px] italic text-muted">„{b.notiz}“</p>{/if}
    </div>

    {#if kategorien && !b.intern}
      <label class="label mt-5" for="b-kat">Kategorie</label>
      <KategorieWahl
        id="b-kat"
        wert={b.kategorie}
        optionen={b.betrag > 0 && !b.rueckzahlung ? kategorien.einnahme : kategorien.ausgabe}
        onwahl={kategorieSetzen}
        onneu={kategorieAnlegen}
      />
      <button class="pill-accent mt-2" disabled={erkennt} onclick={erkennen}>
        <Sparkles size={15} /> {erkennt ? 'Erkenne …' : 'Kategorie erkennen'}
      </button>
      {#if !merkenVorschlag && HERKUNFT[b.kategorie_quelle]}
        <p class="mt-2 px-1 text-[13px] text-muted">{HERKUNFT[b.kategorie_quelle]}</p>
      {/if}
      {#if merkenVorschlag}
        <div class="mt-3 flex items-center gap-3 rounded-2xl bg-accent-soft p-3 text-[14px]">
          <span class="flex-1">Alle Buchungen von „{b.haendler}“ künftig als <b>{merkenVorschlag}</b> einordnen?</span>
          <button class="knopf-primaer !px-3.5 !py-2 text-[14px]" onclick={merken}>Merken</button>
        </div>
      {/if}
    {/if}

    <div class="karte mt-5 divide-y divide-line text-[15px]">
      {#if b.verwendungszweck}
        <div class="px-4 py-3"><div class="text-[13px] text-muted">Verwendungszweck</div><div class="mt-0.5 break-words">{b.verwendungszweck}</div></div>
      {/if}
      {#if b.buchungstext}<div class="flex justify-between px-4 py-3"><span class="text-muted">Art</span><span>{b.buchungstext}</span></div>{/if}
      {#if b.iban_gegenpartei}<div class="flex justify-between gap-4 px-4 py-3"><span class="text-muted">IBAN</span><span class="truncate font-mono text-[13px]">{b.iban_gegenpartei}</span></div>{/if}
      {#if b.glaeubiger_id}<div class="flex justify-between gap-4 px-4 py-3"><span class="text-muted">Gläubiger-ID</span><span class="truncate font-mono text-[13px]">{b.glaeubiger_id}</span></div>{/if}
      {#if b.mandatsreferenz}<div class="flex justify-between gap-4 px-4 py-3"><span class="text-muted">Mandat</span><span class="truncate font-mono text-[13px]">{b.mandatsreferenz}</span></div>{/if}
    </div>

    {#if b.bearbeitbar}
      <form class="karte mt-4 space-y-3 p-4" onsubmit={eigeneSpeichern}>
        <div class="text-[13px] text-muted">Selbst eingetragen – du kannst sie ändern</div>
        <div class="grid grid-cols-2 gap-2">
          <div><label class="label" for="e-datum">Datum</label><DatumFeld id="e-datum" bind:wert={eDatum} /></div>
          <div><label class="label" for="e-betrag">Betrag (€)</label><input id="e-betrag" class="feld" inputmode="decimal" bind:value={eBetrag} /></div>
        </div>
        <div><label class="label" for="e-text">Beschreibung</label><input id="e-text" class="feld" bind:value={eText} /></div>
        <div class="flex gap-2">
          <button class="knopf-primaer flex-1">Speichern</button>
          <button type="button" class="knopf-gefahr" onclick={eigeneLoeschen}>Löschen</button>
        </div>
      </form>
    {/if}

    <div class="karte mt-4 divide-y divide-line text-[15px]">
      <button class="flex w-full items-center gap-3 px-4 py-3 text-left" onclick={() => aendern({ intern: !b.intern })} aria-pressed={b.intern}>
        <ArrowRightLeft size={18} class="shrink-0 text-muted" />
        <span class="flex-1">
          <span class="block">Umbuchung</span>
          <span class="block text-[13px] text-muted">Zwischen eigenen Konten – zählt nicht als Einnahme oder Ausgabe</span>
        </span>
        <span class="relative h-7 w-12 shrink-0 rounded-full transition-colors {b.intern ? 'bg-accent' : 'bg-spur'}">
          <span class="absolute top-0.5 size-6 rounded-full bg-white shadow transition-all {b.intern ? 'left-[22px]' : 'left-0.5'}"></span>
        </span>
      </button>

      {#if !b.intern}
        <button class="flex w-full items-center gap-3 px-4 py-3 text-left" onclick={() => aendern({ ausgeschlossen: !b.ausgeschlossen })} aria-pressed={b.ausgeschlossen}>
          <EyeOff size={18} class="shrink-0 text-muted" />
          <span class="flex-1">
            <span class="block">Nicht berücksichtigen</span>
            <span class="block text-[13px] text-muted">Zählt nirgends mit – weder bei „frei verfügbar“ noch in Analysen und Budgets</span>
          </span>
          <span class="relative h-7 w-12 shrink-0 rounded-full transition-colors {b.ausgeschlossen ? 'bg-accent' : 'bg-spur'}">
            <span class="absolute top-0.5 size-6 rounded-full bg-white shadow transition-all {b.ausgeschlossen ? 'left-[22px]' : 'left-0.5'}"></span>
          </span>
        </button>
      {/if}

      {#if !b.intern && Number(b.betrag) > 0}
        <button class="flex w-full items-center gap-3 px-4 py-3 text-left" onclick={() => aendern({ rueckzahlung: !b.rueckzahlung }, b.rueckzahlung ? 'Zählt wieder als Einnahme' : 'Als Rückzahlung markiert – jetzt die Kategorie der Ausgabe wählen')} aria-pressed={b.rueckzahlung}>
          <Undo2 size={18} class="shrink-0 text-muted" />
          <span class="flex-1">
            <span class="block">Rückzahlung</span>
            <span class="block text-[13px] text-muted">Geld kam zurück (Erstattung, jemand zahlt seinen Teil) – mindert die Ausgaben der gewählten Kategorie, statt als Einnahme zu zählen</span>
          </span>
          <span class="relative h-7 w-12 shrink-0 rounded-full transition-colors {b.rueckzahlung ? 'bg-accent' : 'bg-spur'}">
            <span class="absolute top-0.5 size-6 rounded-full bg-white shadow transition-all {b.rueckzahlung ? 'left-[22px]' : 'left-0.5'}"></span>
          </span>
        </button>
      {/if}

      {#if !b.intern}
        <div class="px-4 py-3">
          <div class="flex items-center gap-3">
            <Receipt size={18} class="shrink-0 text-muted" />
            <span class="flex-1">Steuerliste<span class="block text-[13px] text-muted">{b.steuer ? 'Steht unter Sparen → Steuern' : 'Steht nicht in der Steuerliste'}</span></span>
          </div>
          <div class="mt-2 pl-[30px]">
            <Auswahl optionen={[['', 'Automatisch'], ['ja', 'Ist eine Steuer'], ['nein', 'Gehört nicht hinein']]} wert={b.steuer_wahl} onwahl={(w) => aendern({ steuer: w })} />
          </div>
        </div>
      {/if}

      {#if b.intern}
        <div class="px-4 py-3">
          <div class="text-[13px] text-muted">Gegenbuchung auf dem anderen Konto</div>
          {#if b.gegenbuchung}
            <div class="mt-2 flex items-center gap-3">
              <div class="flex min-w-0 flex-1 items-center gap-3 rounded-2xl bg-card-hi px-3 py-2.5">
                <span class="min-w-0 flex-1">
                  <span class="block truncate">{b.gegenbuchung.konto_name}</span>
                  <span class="block truncate text-[13px] text-muted">{datum(b.gegenbuchung.datum)}{b.gegenbuchung.gegenpartei ? ` · ${b.gegenbuchung.gegenpartei}` : ''}</span>
                </span>
                <Amount wert={b.gegenbuchung.betrag} vorzeichen klasse="shrink-0" />
              </div>
              <button class="text-[14px] font-medium text-accent" onclick={gegenLoesen}>Lösen</button>
            </div>
          {:else if gegenKandidaten === null}
            <button class="pill-accent mt-2" onclick={gegenSuchen}><ArrowRightLeft size={15} /> Gegenbuchung wählen</button>
          {:else if !gegenKandidaten.length}
            <p class="mt-2 text-[13px] text-muted">
              Keine passende Buchung gefunden. Gesucht wird auf deinen anderen Konten nach demselben Betrag mit umgekehrtem
              Vorzeichen, bis zu fünf Tage davor oder danach.
            </p>
          {:else}
            <div class="mt-2 space-y-1.5">
              {#each gegenKandidaten as k (k.id)}
                <button class="flex w-full items-center gap-3 rounded-2xl bg-card-hi px-3 py-2.5 text-left" onclick={() => gegenWaehlen(k)}>
                  <span class="min-w-0 flex-1">
                    <span class="block truncate">{k.konto_name}</span>
                    <span class="block truncate text-[13px] text-muted">{datum(k.datum)}{k.gegenpartei ? ` · ${k.gegenpartei}` : ''}</span>
                  </span>
                  <Amount wert={k.betrag} vorzeichen klasse="shrink-0" />
                </button>
              {/each}
            </div>
          {/if}
        </div>
      {/if}

      <div class="px-4 py-3">
        <div class="text-[13px] text-muted">Zugehöriger Vertrag</div>
        {#if b.vertrag}
          <div class="mt-2 flex items-center gap-3">
            <a href="#/vertrag/{b.vertrag.id}" class="flex min-w-0 flex-1 items-center gap-3 rounded-2xl bg-card-hi px-3 py-2.5" onclick={() => (offen = false)}>
              <KategorieAvatar kategorie={b.vertrag.kategorie} groesse={36} />
              <span class="min-w-0 flex-1">
                <span class="block truncate">{b.vertrag.name}</span>
                <span class="block text-[13px] text-muted">{TURNUS[b.vertrag.turnus]} · {euro(Math.abs(Number(b.vertrag.betrag)))}</span>
              </span>
              <ChevronRight size={18} class="shrink-0 text-faint" />
            </a>
            <button class="text-[14px] font-medium text-accent" onclick={() => aendern({ contract_id: null }, 'Zuordnung gelöst')}>Lösen</button>
          </div>
        {:else}
          <select class="feld mt-2 appearance-none" bind:value={vertragWahl} onfocus={vertraegeLaden} onchange={() => vertragWahl !== 'neu' && vertragZuordnen()}>
            <option value="">Keinem Vertrag zugeordnet</option>
            <option value="neu">＋ Neuen Vertrag aus dieser Buchung anlegen</option>
            {#each vertraege ?? [] as c (c.id)}
              <option value={String(c.id)}>{c.name} · {euro(Math.abs(Number(c.betrag)))}</option>
            {/each}
          </select>
          {#if vertragWahl === 'neu'}
            <div class="mt-2 flex gap-2">
              <select class="feld appearance-none" bind:value={neuerTurnus} aria-label="Rhythmus">
                {#each Object.entries(TURNUS) as [wert, label] (wert)}<option value={wert}>{label}</option>{/each}
              </select>
              <button class="knopf-primaer shrink-0" onclick={vertragZuordnen}>Anlegen</button>
            </div>
          {/if}
        {/if}
      </div>

      <div class="px-4 py-3">
        <label class="text-[13px] text-muted" for="b-tag">Tags</label>
        <div class="mt-2 flex flex-wrap items-center gap-1.5">
          {#each b.tags as tag (tag)}
            <span class="pill bg-accent-soft text-accent">
              #{tag}
              <button aria-label="Tag {tag} entfernen" onclick={() => aendern({ tags: b.tags.filter((t: string) => t !== tag) })}><X size={14} /></button>
            </span>
          {/each}
          <form class="min-w-24 flex-1" onsubmit={(e) => { e.preventDefault(); tagDazu(tagEingabe); }}>
            <input
              id="b-tag"
              class="w-full bg-transparent py-1 outline-none placeholder:text-faint"
              placeholder={b.tags.length ? 'Weiterer Tag' : 'Tag hinzufügen, z. B. Urlaub'}
              autocapitalize="off"
              maxlength="30"
              bind:value={tagEingabe}
            />
          </form>
        </div>
        {#if tagVorschlaege.length}
          <div class="mt-2 flex flex-wrap gap-1.5">
            {#each tagVorschlaege as tag (tag)}
              <button class="pill bg-card-hi text-muted" onclick={() => tagDazu(tag)}>#{tag}</button>
            {/each}
          </div>
        {/if}
      </div>

      <div class="px-4 py-3">
        <label class="text-[13px] text-muted" for="b-notiz">Notiz</label>
        <textarea
          id="b-notiz"
          class="mt-1 block w-full resize-none bg-transparent outline-none placeholder:text-faint"
          rows="2"
          placeholder="Notiz hinzufügen"
          bind:value={notiz}
          onblur={() => notiz.trim() !== b.notiz && aendern({ notiz }, 'Notiz gespeichert')}
        ></textarea>
      </div>
    </div>
  {:else}
    <Laden form="detail" zeilen={2} />
  {/if}
</Sheet>
