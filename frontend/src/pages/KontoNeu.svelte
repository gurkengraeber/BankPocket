<script lang="ts">
  import { ChevronRight, PenLine, Search, Upload } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import BankAvatar from '../components/BankAvatar.svelte';
  import Header from '../components/Header.svelte';
  import Sheet from '../components/Sheet.svelte';
  import { api } from '../lib/api';
  import { gehe, route } from '../lib/router.svelte';
  import { fehler, toast } from '../lib/store.svelte';

  const GRUPPEN: [string, string][] = [
    ['Tägliche Konten', 'giro'],
    ['Sparkonten', 'spar'],
    ['Crypto', 'krypto'],
    ['Virtuell', 'virtuell'],
  ];

  // Meistgenutzte Quellen: [Kachel, Name, Ziel auf der Verbinden-Seite]
  const BELIEBT: [string, string, string][] = [
    ['sparkasse', 'Sparkasse', '?q=Sparkasse%20'],
    ['volksbank', 'Volksbank', '?q=Volksbank%20'],
    ['ing', 'ING', '?bank=ing'],
    ['dkb', 'DKB', '?q=12030000'],
    ['comdirect', 'comdirect', '?q=20041155'],
    ['consorsbank', 'Consorsbank', '?bank=consorsbank'],
    ['trade_republic', 'Trade Republic', '?quelle=trade_republic'],
    ['norwegian', 'Bank Norwegian', '?quelle=enablebanking'],
    ['binance', 'Binance', '?quelle=binance'],
  ];

  let manuellOffen = $state(false);
  let splitwiseOffen = $state(false);
  let csvOffen = $state(route.query.get('csv') === '1');
  let name = $state('');
  let gruppe = $state('Tägliche Konten');
  let konten = $state<any[]>([]);
  let csvKonto = $state<number | 'neu'>('neu');
  let csvName = $state('');
  let trenner = $state(';');
  let datei = $state<FileList | null>(null);
  let laeuft = $state(false);

  async function manuellAnlegen(e: SubmitEvent) {
    e.preventDefault();
    try {
      const typ = GRUPPEN.find(([g]) => g === gruppe)![1];
      await api('/accounts', { body: { name, quelle: 'manuell', typ, gruppe } });
      toast('Konto angelegt');
      gehe('/');
    } catch (err) {
      fehler(err);
    }
  }

  // Die Splitwise-API gibt es nur mit Pro-Zugang – darum ein manuelles Konto, bei dem man den Stand einträgt
  async function splitwiseAnlegen() {
    try {
      const d = await api('/accounts');
      const da = d.gruppen.flatMap((g: any) => g.konten).find((k: any) => k.manuell && k.name.toLowerCase() === 'splitwise');
      const id = da?.id ?? (await api('/accounts', { body: { name: 'Splitwise', quelle: 'manuell', typ: 'virtuell', gruppe: 'Virtuell' } })).id;
      gehe(`/konto/${id}?stand=1`);
    } catch (err) {
      fehler(err);
    }
  }

  // PayPal hat keinen Abruf für Privatkonten – der Weg führt über den CSV-Export der Aktivitäten
  function paypalOeffnen() {
    const da = konten.find((k) => k.quelle === 'paypal');
    csvKonto = da?.id ?? 'neu';
    csvName = 'PayPal';
    trenner = ',';
    csvOffen = true;
  }

  async function importieren(e: SubmitEvent) {
    e.preventDefault();
    if (!datei?.length) return;
    laeuft = true;
    try {
      let id = csvKonto;
      if (id === 'neu') {
        const quelle = csvName.toLowerCase().includes('paypal') ? 'paypal' : csvName.toLowerCase().includes('norwegian') ? 'norwegian' : 'csv';
        const typ = quelle === 'norwegian' ? 'kreditkarte' : 'giro';
        id = (await api('/accounts', { body: { name: csvName, quelle, typ, gruppe: 'Tägliche Konten' } })).id;
      }
      const form = new FormData();
      form.append('file', datei[0]);
      const r = await api(`/accounts/${id}/import?delimiter=${encodeURIComponent(trenner)}`, { form });
      toast(r.depot ? `Depot mit ${r.importiert} Positionen importiert` : `${r.importiert} Buchungen importiert${r.duplikate ? `, ${r.duplikate} schon vorhanden` : ''}`);
      gehe(`/konto/${id}`);
    } catch (err) {
      fehler(err);
    } finally {
      laeuft = false;
    }
  }

  onMount(() => {
    api('/accounts')
      .then((d) => (konten = d.gruppen.flatMap((g: any) => g.konten).filter((k: any) => !k.manuell && !k.connection_id)))
      .catch(fehler);
  });
</script>

<div class="px-4">
  <Header titel="Konto hinzufügen" gross={false} zurueckZu="#/" />

  <h2 class="abschnitt !pt-3">Automatisch abrufen</h2>
  <p class="px-1 pb-3 text-[14px] text-muted">Einmal verbinden – Umsätze und Stände kommen danach von selbst.</p>
  <div class="grid grid-cols-3 gap-2 sm:grid-cols-4">
    {#each BELIEBT as [quelle, name, ziel] (name)}
      <a class="karte flex flex-col items-center gap-2 px-2 py-3.5 text-center active:bg-card-hi" href="#/verbinden{ziel}">
        <BankAvatar {quelle} {name} />
        <span class="text-[13px] font-medium leading-tight">{name}</span>
      </a>
    {/each}
  </div>
  <div class="karte mt-2 overflow-hidden">
    <a class="zeile" href="#/verbinden">
      <span class="grid size-11 shrink-0 place-items-center rounded-[14px] bg-accent text-accent-ink"><Search size={21} /></span>
      <span class="flex-1">
        <span class="block text-[17px] font-medium">Andere Bank suchen</span>
        <span class="text-[13px] text-muted">Nach Name, Ort, BLZ oder IBAN – Postbank, Deutsche Bank & viele mehr</span>
      </span>
      <ChevronRight size={20} class="text-faint" />
    </a>
  </div>

  <h2 class="abschnitt">Selbst eintragen</h2>
  <p class="px-1 pb-3 text-[14px] text-muted">Für alles ohne Bankzugang.</p>
  <div class="karte overflow-hidden">
    <button class="zeile" onclick={() => (manuellOffen = true)}>
      <span class="grid size-11 shrink-0 place-items-center rounded-[14px] bg-card-hi text-text"><PenLine size={21} /></span>
      <span class="flex-1">
        <span class="block text-[17px] font-medium">Manuelles Konto</span>
        <span class="text-[13px] text-muted">Bargeld, Kautionen, Schulden, Wallets – du trägst Buchungen selbst ein</span>
      </span>
      <ChevronRight size={20} class="text-faint" />
    </button>
    <button class="zeile" onclick={() => (splitwiseOffen = true)}>
      <BankAvatar quelle="splitwise" name="Splitwise" />
      <span class="flex-1">
        <span class="block text-[17px] font-medium">Splitwise</span>
        <span class="text-[13px] text-muted">Wer wem was schuldet – Stand eintragen oder mit Pro automatisch</span>
      </span>
      <ChevronRight size={20} class="text-faint" />
    </button>
    <button class="zeile" onclick={paypalOeffnen}>
      <BankAvatar quelle="paypal" name="PayPal" />
      <span class="flex-1">
        <span class="block text-[17px] font-medium">PayPal</span>
        <span class="text-[13px] text-muted">Aktivitäten bei PayPal als CSV herunterladen und hier importieren</span>
      </span>
      <ChevronRight size={20} class="text-faint" />
    </button>
    <button class="zeile" onclick={() => (csvOffen = true)}>
      <span class="grid size-11 shrink-0 place-items-center rounded-[14px] bg-card-hi text-text"><Upload size={21} /></span>
      <span class="flex-1">
        <span class="block text-[17px] font-medium">Kontoauszug importieren</span>
        <span class="text-[13px] text-muted">CSV-Export vom Konto oder eine Depotübersicht</span>
      </span>
      <ChevronRight size={20} class="text-faint" />
    </button>
  </div>
</div>

<Sheet bind:offen={splitwiseOffen} titel="Splitwise">
  <div class="karte overflow-hidden">
    <button class="zeile" onclick={splitwiseAnlegen}>
      <span class="flex-1">
        <span class="block text-[17px] font-medium">Stand selbst eintragen</span>
        <span class="text-[13px] text-muted">Funktioniert ohne Pro – du tippst ein, was du bekommst oder schuldest</span>
      </span>
      <ChevronRight size={20} class="text-faint" />
    </button>
    <a class="zeile" href="#/verbinden?quelle=splitwise">
      <span class="flex-1">
        <span class="block text-[17px] font-medium">Automatisch abrufen</span>
        <span class="text-[13px] text-muted">Per API-Schlüssel – braucht Splitwise Pro</span>
      </span>
      <ChevronRight size={20} class="text-faint" />
    </a>
  </div>
</Sheet>

<Sheet bind:offen={manuellOffen} titel="Manuelles Konto">
  <form class="space-y-4" onsubmit={manuellAnlegen}>
    <div><label class="label" for="m-name">Name</label><input id="m-name" class="feld" placeholder="z. B. Bargeld" bind:value={name} /></div>
    <div>
      <label class="label" for="m-gruppe">Gruppe</label>
      <select id="m-gruppe" class="feld appearance-none" bind:value={gruppe}>
        {#each GRUPPEN as [g] (g)}<option value={g}>{g}</option>{/each}
      </select>
    </div>
    <button class="knopf-primaer w-full" disabled={!name}>Anlegen</button>
  </form>
</Sheet>

<Sheet bind:offen={csvOffen} titel="Kontoauszug importieren">
  <form class="space-y-4" onsubmit={importieren}>
    <div>
      <label class="label" for="c-konto">In welches Konto?</label>
      <select id="c-konto" class="feld appearance-none" bind:value={csvKonto}>
        <option value="neu">Neues Konto anlegen …</option>
        {#each konten as k (k.id)}<option value={k.id}>{k.name}</option>{/each}
      </select>
    </div>
    {#if csvKonto === 'neu'}
      <div><label class="label" for="c-name">Name des Kontos</label><input id="c-name" class="feld" placeholder="z. B. Norwegian Kreditkarte" bind:value={csvName} /></div>
    {/if}
    <div>
      <label class="label" for="c-datei">CSV-Datei</label>
      <input id="c-datei" class="feld file:mr-3 file:rounded-lg file:border-0 file:bg-card-hi file:px-3 file:py-1.5 file:text-text" type="file" accept=".csv,text/csv" bind:files={datei} />
    </div>
    <div>
      <label class="label" for="c-trenner">Trennzeichen</label>
      <select id="c-trenner" class="feld appearance-none" bind:value={trenner}>
        <option value=";">Semikolon ( ; ) – deutsche Banken</option>
        <option value=",">Komma ( , )</option>
      </select>
    </div>
    <button class="knopf-primaer w-full" disabled={!datei?.length || (csvKonto === 'neu' && !csvName) || laeuft}>Importieren</button>
  </form>
</Sheet>
