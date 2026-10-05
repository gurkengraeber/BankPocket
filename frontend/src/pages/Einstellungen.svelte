<script lang="ts">
  import { ArrowUpDown, Bell, ChevronRight, Clock, Eye, LogOut, PieChart, Plus, ShieldCheck, Sparkles, Tags, TriangleAlert, Upload } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import BankAvatar from '../components/BankAvatar.svelte';
  import Header from '../components/Header.svelte';
  import Startbildschirm from '../components/Startbildschirm.svelte';
  import { api } from '../lib/api';
  import { zeitpunkt } from '../lib/format';
  import { pushAktivieren, pushDeaktivieren, pushZustand, type PushZustand } from '../lib/push';
  import { auth, budgetsUmschalten, fehler, toast, ui, versteckenUmschalten } from '../lib/store.svelte';
  import { thema, themaSetzen, type Thema } from '../lib/thema.svelte';

  const STATUS: Record<string, [string, string]> = {
    ok: ['Aktiv', 'text-pos'],
    neu: ['Bereit', 'text-muted'],
    laeuft: ['Aktualisiert …', 'text-muted'],
    fehler: ['Fehler', 'text-neg'],
    freigabe_noetig: ['Freigabe nötig', 'text-warn'],
    auswahl_noetig: ['Auswahl nötig', 'text-warn'],
    pin_falsch: ['Zugang prüfen', 'text-neg'],
    gesperrt: ['Gesperrt', 'text-neg'],
  };

  let verbindungen = $state<any[]>([]);
  let einst = $state<any>(null);
  let push = $state<PushZustand | 'pruefe'>('pruefe');
  let pushArbeitet = $state(false);
  let ki = $state<any>(null);
  let kiSchluessel = $state('');
  let kiArbeitet = $state(false);
  let eigeneNamen = $state('');
  let namenArbeitet = $state(false);

  async function namenSpeichern(e: SubmitEvent) {
    e.preventDefault();
    namenArbeitet = true;
    try {
      const r = await api('/einstellungen/eigene-namen', { method: 'PUT', body: { namen: eigeneNamen } });
      eigeneNamen = r.eigene_namen;
      toast(r.neu_markiert ? `${r.neu_markiert} Buchungen als Umbuchung markiert` : 'Gespeichert');
    } catch (err) {
      fehler(err);
    } finally {
      namenArbeitet = false;
    }
  }

  async function kiSpeichern(body: Record<string, unknown>) {
    kiArbeitet = true;
    try {
      ki = await api('/ki', { method: 'PUT', body });
      kiSchluessel = '';
    } catch (e) {
      fehler(e);
    } finally {
      kiArbeitet = false;
    }
  }

  async function kiEinordnen() {
    kiArbeitet = true;
    try {
      ki = await api('/ki/einordnen', { method: 'POST' });
      toast(ki.neu_eingeordnet ? `${ki.neu_eingeordnet} Händler eingeordnet` : 'Nichts Neues zum Einordnen');
    } catch (e) {
      fehler(e);
    } finally {
      kiArbeitet = false;
    }
  }

  async function kiVergessen() {
    if (!confirm('Alle Einordnungen der KI verwerfen? Deine eigenen Regeln bleiben.')) return;
    await api('/ki/ergebnisse', { method: 'DELETE' }).catch(fehler);
    ki = await api('/ki');
  }

  async function pushUmschalten() {
    pushArbeitet = true;
    try {
      if (push === 'an') await pushDeaktivieren();
      else await pushAktivieren();
      push = await pushZustand();
      toast(push === 'an' ? 'Push-Benachrichtigungen aktiv' : 'Push-Benachrichtigungen aus');
    } catch (e) {
      fehler(e);
      push = await pushZustand();
    } finally {
      pushArbeitet = false;
    }
  }

  async function pushTest() {
    try {
      const r = await api('/push/test', { method: 'POST' });
      toast(r.gesendet ? 'Test gesendet – gleich sollte eine Benachrichtigung kommen' : 'Kein Gerät angemeldet', r.gesendet ? 'ok' : 'fehler');
    } catch (e) {
      fehler(e);
    }
  }

  async function abmelden() {
    await api('/logout', { method: 'POST' }).catch(() => {});
    auth.angemeldet = false;
  }

  let sichert = $state(false);
  async function jetztSichern() {
    sichert = true;
    try {
      einst.sicherung = await api('/sicherung', { method: 'POST' });
      if (einst.sicherung.fehler) fehler(einst.sicherung.fehler);
      else toast('Sicherung geschrieben');
    } catch (e) {
      fehler(e);
    }
    sichert = false;
  }

  onMount(async () => {
    api('/verbindungen').then((v) => (verbindungen = v)).catch(fehler);
    api('/einstellungen').then((e) => ((einst = e), (eigeneNamen = e.eigene_namen ?? ''))).catch(fehler);
    api('/ki').then((k) => (ki = k)).catch(fehler);
    push = await pushZustand();
  });
</script>

<div class="px-4">
  <Header titel="Einstellungen" zurueckZu="#/" />

  <h2 class="abschnitt !pt-2">Bankverbindungen</h2>
  <div class="karte overflow-hidden">
    {#each verbindungen as v (v.id)}
      {@const [label, farbe] = STATUS[v.status] ?? [v.status, 'text-muted']}
      <a class="zeile" href="#/verbindung/{v.id}">
        <BankAvatar quelle={v.bank} name={v.name} />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-[17px]">{v.name}</span>
          <span class="text-[13px] {farbe}">{label}{v.status === 'ok' ? ` · ${zeitpunkt(v.letzter_erfolg)}` : ''}</span>
        </span>
        <ChevronRight size={20} class="text-faint" />
      </a>
    {/each}
    <a class="zeile" href="#/konto-neu">
      <span class="grid size-11 place-items-center rounded-[14px] bg-accent-soft text-accent"><Plus size={22} /></span>
      <span class="flex-1 text-[17px] text-accent">Bank verbinden</span>
    </a>
  </div>

  <h2 class="abschnitt">Darstellung</h2>
  <div class="grid grid-cols-3 gap-1 rounded-2xl bg-card p-1">
    {#each [['auto', 'Automatisch'], ['hell', 'Hell'], ['dunkel', 'Dunkel']] as [wert, label] (wert)}
      <button
        class="rounded-xl py-2.5 text-[15px] font-semibold transition-colors {thema.wahl === wert ? 'bg-card-hi text-text' : 'text-muted'}"
        aria-pressed={thema.wahl === wert}
        onclick={() => themaSetzen(wert as Thema)}>{label}</button
      >
    {/each}
  </div>

  <Startbildschirm klasse="mt-3 w-full justify-center" />

  <h2 class="abschnitt">Benachrichtigungen</h2>
  <div class="karte p-4">
    <div class="flex items-start gap-3">
      <Bell size={22} class="mt-0.5 shrink-0 text-accent" />
      <div class="flex-1 text-[15px]">
        <div class="font-semibold">Push aufs Handy</div>
        <p class="mt-1 text-[13px] leading-relaxed text-muted">
          Bei Freigaben (alle 3–6 Monate), neuen Verträgen, Preiserhöhungen und überfälligen Zahlungen.
        </p>
      </div>
    </div>
    {#if push === 'nicht_moeglich'}
      <p class="mt-4 rounded-xl bg-card-hi p-3 text-[13px] leading-relaxed text-muted">
        Push braucht eine HTTPS-Verbindung zu deinem Server. Richte dafür Tailscale ein (Anleitung im README) – bis dahin
        erscheinen alle Hinweise hier in der App unter der Glocke.
      </p>
    {:else if push === 'blockiert'}
      <p class="mt-4 rounded-xl bg-warn-soft p-3 text-[13px] text-warn">Benachrichtigungen sind blockiert. Erlaube sie in den Website-Einstellungen deines Browsers.</p>
    {:else if push !== 'pruefe'}
      <div class="mt-4 flex gap-2">
        <button class="{push === 'an' ? 'knopf-sekundaer' : 'knopf-primaer'} flex-1 !py-3" disabled={pushArbeitet} onclick={pushUmschalten}>
          {push === 'an' ? 'Deaktivieren' : 'Aktivieren'}
        </button>
        {#if push === 'an'}<button class="knopf-sekundaer flex-1 !py-3" onclick={pushTest}>Test senden</button>{/if}
      </div>
    {/if}
  </div>

  <h2 class="abschnitt">Automatische Abrufe</h2>
  <div class="karte p-4 text-[15px]">
    <div class="flex items-start gap-3">
      <Clock size={22} class="mt-0.5 shrink-0 text-accent" />
      <div>
        {#if einst}
          <div>Täglich um {einst.abrufzeiten.join(', ')} Uhr</div>
          {#if einst.naechster_abruf}<div class="mt-1 text-[13px] text-muted">Nächster Abruf: {zeitpunkt(einst.naechster_abruf)}</div>{/if}
          {#if !einst.automatisch}<div class="mt-1 text-[13px] text-warn">Automatische Abrufe sind ausgeschaltet.</div>{/if}
        {/if}
      </div>
    </div>
    {#if einst && !einst.produkt_id_gesetzt}
      <div class="mt-4 flex gap-2.5 rounded-xl bg-warn-soft p-3 text-[13px] leading-relaxed text-warn">
        <TriangleAlert size={18} class="shrink-0" />
        <span>FinTS-Produkt-ID fehlt – ohne sie können keine Banken abgerufen werden. Trage sie in der .env als BANKPOCKET_FINTS_PRODUCT_ID ein.</span>
      </div>
    {/if}
  </div>

  <h2 class="abschnitt">Sicherung</h2>
  <div class="karte p-4 text-[15px]">
    <div class="flex items-start gap-3">
      <ShieldCheck size={22} class="mt-0.5 shrink-0 text-accent" />
      <div class="min-w-0 flex-1">
        {#if einst}
          {@const b = einst.sicherung}
          <div class="font-semibold">
            {b.zuletzt ? `Zuletzt gesichert: ${zeitpunkt(b.zuletzt)}` : 'Noch keine Sicherung'}
          </div>
          <p class="mt-1 text-[13px] leading-relaxed text-muted">
            Einmal täglich, Datenbank samt Schlüsseldateien.
            {#if b.zuletzt}
              {b.verschluesselt ? 'Verschlüsselt' : 'Unverschlüsselt'}{b.hochgeladen ? ` und nach ${b.ziel} hochgeladen.` : ', nur auf dem Server.'}
            {/if}
          </p>
          {#if b.fehler}
            <p class="mt-2 rounded-xl bg-warn-soft p-3 text-[13px] text-warn">Letzter Versuch fehlgeschlagen: {b.fehler}</p>
          {:else if !b.passwort_gesetzt || !b.ziel}
            <p class="mt-2 rounded-xl bg-card-hi p-3 text-[13px] leading-relaxed text-muted">
              Geht die Festplatte des Servers kaputt, ist auch diese Sicherung weg. Für eine verschlüsselte Kopie in der
              Cloud in der .env BANKPOCKET_BACKUP_PASSWORT und BANKPOCKET_BACKUP_ZIEL eintragen (siehe README).
            </p>
          {/if}
        {/if}
      </div>
    </div>
    <button class="knopf-sekundaer mt-4 w-full !py-3" disabled={sichert} onclick={jetztSichern}>{sichert ? 'Sichere …' : 'Jetzt sichern'}</button>
  </div>

  <h2 class="abschnitt">Kategorien mit KI</h2>
  <div class="karte p-4">
    <div class="flex items-start gap-3">
      <Sparkles size={22} class="mt-0.5 shrink-0 text-accent" />
      <div class="flex-1 text-[15px]">
        <div class="font-semibold">Mistral ordnet unbekannte Händler ein</div>
        <p class="mt-1 text-[13px] leading-relaxed text-muted">
          Nur für Händler, die keine Regel erkennt – jeder wird einmal gefragt. Gesendet werden nur Händlername und
          gekürzter Verwendungszweck, ohne IBAN, Beträge oder Nummern. Überweisungen an Privatpersonen bleiben hier.
        </p>
      </div>
    </div>
    {#if ki}
      {#if ki.schluessel_gesetzt}
        <button class="zeile -mx-4 mt-2 w-[calc(100%+2rem)] !px-4" disabled={kiArbeitet} onclick={() => kiSpeichern({ aktiv: !ki.aktiv })}>
          <span class="flex-1 text-[15px]">Nach jedem Abruf automatisch</span>
          <span class="relative h-7 w-12 rounded-full transition-colors {ki.aktiv ? 'bg-accent' : 'bg-line'}">
            <span class="absolute top-0.5 size-6 rounded-full bg-white shadow transition-all {ki.aktiv ? 'left-[22px]' : 'left-0.5'}"></span>
          </span>
        </button>
        {#if ki.letzte_meldung}
          <p class="mt-2 rounded-xl bg-warn-soft p-3 text-[13px] text-warn">{ki.letzte_meldung}</p>
        {/if}
        <div class="mt-3 text-[13px] text-muted">{ki.eingeordnet} Händler eingeordnet · {ki.offen} offen</div>
        <div class="mt-3 flex gap-2">
          <button class="knopf-primaer flex-1 !py-3" disabled={kiArbeitet || !ki.offen} onclick={kiEinordnen}>
            {kiArbeitet ? 'Ordnet ein …' : 'Jetzt einordnen'}
          </button>
          <button class="knopf-sekundaer !py-3" disabled={kiArbeitet} onclick={() => kiSpeichern({ schluessel: '', aktiv: false })}>Schlüssel entfernen</button>
        </div>
        {#if ki.eingeordnet}
          <button class="mt-3 text-[13px] font-medium text-accent" onclick={kiVergessen}>KI-Einordnungen zurücksetzen</button>
        {/if}
      {:else}
        <form class="mt-4 space-y-3" onsubmit={(e) => { e.preventDefault(); kiSpeichern({ schluessel: kiSchluessel, aktiv: true }); }}>
          <div>
            <label class="label" for="ki-key">API-Schlüssel von console.mistral.ai</label>
            <input id="ki-key" class="feld" type="password" placeholder="API-Schlüssel" autocomplete="off" spellcheck="false" bind:value={kiSchluessel} />
          </div>
          <button class="knopf-primaer w-full !py-3" disabled={!kiSchluessel || kiArbeitet}>Speichern</button>
          <p class="text-[12px] leading-relaxed text-faint">Der Schlüssel wird verschlüsselt auf deinem Server gespeichert. Mistral ist ein europäischer Anbieter. Kosten: anfangs einmalig wenige Cent, danach meist unter 10 Cent im Monat.</p>
        </form>
      {/if}
    {/if}
  </div>

  <h2 class="abschnitt">Umbuchungen</h2>
  <form class="karte space-y-3 p-4" onsubmit={namenSpeichern}>
    <div>
      <label class="label" for="e-namen">Dein Name, wie er bei Überweisungen steht</label>
      <input id="e-namen" class="feld" placeholder="z. B. Max Mustermann" autocomplete="off" bind:value={eigeneNamen} />
    </div>
    <p class="text-[13px] leading-relaxed text-muted">
      Buchungen mit diesem Namen als Absender oder Empfänger zählen als Umbuchung zwischen deinen Konten – nicht als
      Einnahme oder Ausgabe. Mehrere Schreibweisen mit Komma trennen. Was du bei einer Buchung selbst festgelegt hast,
      bleibt so.
    </p>
    <button class="knopf-primaer w-full !py-3" disabled={namenArbeitet}>Speichern</button>
  </form>

  <h2 class="abschnitt">Darstellung & Daten</h2>
  <div class="karte overflow-hidden">
    <button class="zeile" onclick={versteckenUmschalten}>
      <Eye size={22} class="text-accent" />
      <span class="flex-1 text-[17px]">Beträge ausblenden</span>
      <span class="relative h-7 w-12 rounded-full transition-colors {ui.versteckt ? 'bg-accent' : 'bg-line'}">
        <span class="absolute top-0.5 size-6 rounded-full bg-white shadow transition-all {ui.versteckt ? 'left-[22px]' : 'left-0.5'}"></span>
      </span>
    </button>
    <button class="zeile" onclick={budgetsUmschalten}>
      <PieChart size={22} class="text-accent" />
      <span class="flex-1 text-[17px]">Budgets in der Übersicht zeigen</span>
      <span class="relative h-7 w-12 rounded-full transition-colors {ui.budgetsAus ? 'bg-line' : 'bg-accent'}">
        <span class="absolute top-0.5 size-6 rounded-full bg-white shadow transition-all {ui.budgetsAus ? 'left-0.5' : 'left-[22px]'}"></span>
      </span>
    </button>
    <a class="zeile" href="#/konten-sortieren">
      <ArrowUpDown size={22} class="text-accent" />
      <span class="flex-1 text-[17px]">Konten sortieren</span>
      <ChevronRight size={20} class="text-faint" />
    </a>
    <a class="zeile" href="#/kategorien">
      <Tags size={22} class="text-accent" />
      <span class="flex-1 text-[17px]">Kategorien & Regeln</span>
      <ChevronRight size={20} class="text-faint" />
    </a>
    <a class="zeile" href="#/unklar">
      <Sparkles size={22} class="text-accent" />
      <span class="flex-1 text-[17px]">Unklare Buchungen zuordnen</span>
      <ChevronRight size={20} class="text-faint" />
    </a>
    <a class="zeile" href="#/konto-neu?csv=1">
      <Upload size={22} class="text-accent" />
      <span class="flex-1 text-[17px]">Kontoauszug importieren (CSV)</span>
      <ChevronRight size={20} class="text-faint" />
    </a>
  </div>

  {#if auth.aktiv}
    <button class="knopf-sekundaer mt-8 w-full" onclick={abmelden}><LogOut size={18} /> Abmelden</button>
  {/if}
  <p class="mt-8 text-center text-[12px] text-faint">BankPocket · läuft auf deinem eigenen Server</p>
</div>
