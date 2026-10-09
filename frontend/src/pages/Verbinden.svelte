<script lang="ts">
  import { ChevronRight, Eye, EyeOff, Search, ShieldCheck } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import BankAvatar from '../components/BankAvatar.svelte';
  import Header from '../components/Header.svelte';
  import { api } from '../lib/api';
  import { gehe, route } from '../lib/router.svelte';
  import { fehler } from '../lib/store.svelte';

  type Quelle = {
    name: string;
    login: string | null;
    loginPlatzhalter?: string;
    loginModus?: 'tel' | 'text';
    pin: string;
    pinModus?: 'numeric' | 'text';
    pinMehrzeilig?: boolean;
    redirect?: boolean;
    anleitung: string[];
    hinweis: string;
  };

  // Banken über Enable Banking (Kürzel wie im Backend)
  const EB_BANKEN: Record<string, string> = { norwegian: 'Bank Norwegian', consorsbank: 'Consorsbank', n26: 'N26', revolut: 'Revolut',
    commerzbank: 'Commerzbank', santander: 'Santander', bunq: 'bunq', wise: 'Wise' };
  const ebBank = EB_BANKEN[route.query.get('bank') ?? ''] ? route.query.get('bank')! : 'norwegian';
  const EB_NAME = EB_BANKEN[ebBank];
  // Anleitung, wenn Enable Banking schon für eine andere Bank eingerichtet ist (Zugangsdaten werden mitgenutzt)
  const EB_WEITERE = [
    'Im Control Panel von enablebanking.com deine Anwendung öffnen.',
    `Dort dein Konto bei ${EB_NAME} (Deutschland) verknüpfen („link accounts“) – sonst lehnt Enable Banking die Freigabe ab.`,
    'Hier auf „Verbinden“ tippen und den Zugriff bei der Bank bestätigen.',
  ];

  const QUELLEN: Record<string, Quelle> = {
    trade_republic: {
      name: 'Trade Republic',
      login: 'Handynummer mit Ländervorwahl (+49 …)',
      loginPlatzhalter: '+49 170 1234567',
      loginModus: 'tel',
      pin: 'PIN (4 Ziffern)',
      pinModus: 'numeric',
      anleitung: [],
      hinweis:
        'Trade Republic verlangt die Handynummer mit Ländervorwahl, z. B. +49 170 1234567. Gleich bestätigst du die Anmeldung in der Trade-Republic-App oder gibst den Code aus deiner Authenticator-App ein. Trade Republic hat keine offizielle Schnittstelle – BankPocket nutzt dieselbe wie die Web-App (über pytr). Das kann gelegentlich brechen, wenn Trade Republic etwas ändert.',
    },
    binance: {
      name: 'Binance',
      login: 'API-Key',
      pin: 'Secret Key',
      anleitung: [
        'In der Binance-App oder auf binance.com: Profil → API-Verwaltung → API erstellen („System generated“).',
        'Nur „Lesen“ (Enable Reading) aktiv lassen – Handel und Auszahlungen ausschalten.',
        'Optional: Zugriff auf die IP deines Heimanschlusses beschränken.',
        'API-Key und Secret Key hier einfügen.',
      ],
      hinweis: 'Mit einem reinen Lese-Schlüssel kann BankPocket nichts handeln oder auszahlen – nur Guthaben ansehen.',
    },
    enablebanking: {
      name: EB_NAME,
      login: 'Application-ID',
      pin: 'Privater Schlüssel (.pem)',
      pinMehrzeilig: true,
      redirect: true,
      anleitung: [
        'Auf enablebanking.com kostenlos anmelden und im Control Panel eine neue Anwendung für „Production“ registrieren (Haken bei Privatnutzung / „link accounts“).',
        'Als Redirect-URL die unten angezeigte Adresse eintragen. Der private Schlüssel wird dabei als .pem-Datei heruntergeladen.',
        `Die Anwendung aktivieren, indem du deine eigenen Konten verknüpfst („Activate by linking accounts“, ${EB_NAME}, Deutschland).`,
        'Application-ID und den gesamten Inhalt der .pem-Datei hier einfügen.',
      ],
      hinweis:
        `Enable Banking ist ein zugelassener Kontoinformationsdienst. Gleich öffnest du einen Link und bestätigst den Zugriff bei ${EB_NAME} – auf dem Handy auch direkt in der Banking-App. Danach je nach Bank alle 90 bis 180 Tage erneut. BankPocket kann nur lesen.`,
    },
    splitwise: {
      name: 'Splitwise',
      login: null,
      pin: 'API-Schlüssel',
      anleitung: [
        'Am Computer secure.splitwise.com/apps öffnen und anmelden.',
        '„Register your application“ – Name und Adresse sind egal, z. B. „BankPocket“ und http://localhost.',
        'Den „API key“ kopieren und hier einfügen.',
      ],
      hinweis: 'Der API-Zugang funktioniert nur mit Splitwise Pro. Ohne Pro: zurück und „Splitwise“ wählen – dort trägst du den Stand selbst ein. BankPocket liest nur, wer wem was schuldet, und deine geteilten Ausgaben.',
    },
  };
  const LOGIN_LABEL: Record<string, string> = {
    ing: 'Zugangsnummer',
    consorsbank: 'Kontonummer mit 001 am Ende',
    sparkasse: 'Anmeldename oder Legitimations-ID',
    volksbank: 'VR-NetKey oder Alias',
    dkb: 'Anmeldename',
    comdirect: 'Zugangsnummer',
  };
  // Name der App, in der die Bank den Zugriff freigeben lässt
  const FREIGABE_APP: Record<string, string> = {
    ing: 'ING-App',
    consorsbank: 'SecurePlus-App',
    sparkasse: 'S-pushTAN-App',
    volksbank: 'SecureGo-plus-App',
    dkb: 'DKB-App',
    comdirect: 'comdirect-App',
  };
  const SCHNELLWAHL = [
    { label: 'Sparkasse', q: 'Sparkasse ' },
    { label: 'Volksbank & Raiffeisenbank', q: 'Volksbank ' },
    { label: 'DKB', q: '12030000' },
    { label: 'comdirect', q: '20041155' },
    { label: 'Postbank', q: 'Postbank ' },
  ];

  const vorwahl = route.query.get('quelle');
  let banken = $state<any[]>([]);
  let bank = $state<any>(vorwahl && QUELLEN[vorwahl] ? { id: vorwahl, name: QUELLEN[vorwahl].name, art: vorwahl } : null);
  let login = $state('');
  let pin = $state('');
  let blz = $state('');
  let url = $state('');
  let zeigen = $state(false);
  let ebVorhanden = $state(false);
  // Enable Banking nimmt nur https – ohne HTTPS dient https://localhost als Ziel (Adresse danach einfügen)
  const redirectUrl = `${window.location.protocol === 'https:' ? window.location.origin : 'https://localhost'}/api/enablebanking/callback`;
  let sendet = $state(false);
  let suche = $state('');
  let treffer = $state<any[]>([]);
  let sucheFeld = $state<HTMLInputElement>();
  let timer: ReturnType<typeof setTimeout>;

  function suchen(q: string) {
    suche = q;
    clearTimeout(timer);
    if (q.trim().length < 2) {
      treffer = [];
      return;
    }
    timer = setTimeout(async () => {
      try {
        const r = await api(`/banken/suche?q=${encodeURIComponent(q)}`);
        if (q === suche) treffer = r;
      } catch (err) {
        fehler(err);
      }
    }, 200);
  }

  function schnellwahl(q: string) {
    suchen(q);
    sucheFeld?.focus();
  }

  function waehlen(t: any) {
    bank = { id: 'andere', familie: t.familie, name: t.name, blz: t.blz, ort: t.ort };
  }

  const quelle = $derived(bank?.art ? QUELLEN[bank.art] : null);
  const familie = $derived(bank?.familie ?? bank?.id);
  // Enable Banking schon eingerichtet? Dann braucht es weder Application-ID noch Schlüssel
  const mitnutzen = $derived(bank?.art === 'enablebanking' && ebVorhanden);
  const bereit = $derived(mitnutzen || (!!pin && (quelle ? !quelle.login || !!login : !!login)));

  async function verbinden(e: SubmitEvent) {
    e.preventDefault();
    sendet = true;
    try {
      const body = bank.art
        ? { art: bank.art, bank: bank.art === 'enablebanking' ? ebBank : undefined, login: mitnutzen ? '' : login, pin: mitnutzen ? '' : pin }
        : bank.blz
          ? { art: 'fints', bank: 'andere', login, pin, blz: bank.blz, name: bank.name }
          : { art: 'fints', bank: bank.id, login, pin, blz: blz || undefined, url: url || undefined };
      const r = await api('/verbindungen', { body });
      pin = '';
      gehe(`/verbindung/${r.id}?neu=1`);
    } catch (err) {
      fehler(err);
    } finally {
      sendet = false;
    }
  }

  onMount(() => {
    // Einstieg über die Kacheln auf „Konto hinzufügen“: Bank direkt wählen oder die Suche vorbelegen
    const q = route.query.get('q');
    if (q) schnellwahl(q);
    api('/banken')
      .then((b) => {
        banken = b;
        bank ??= b.find((x: any) => x.id === route.query.get('bank')) ?? null;
      })
      .catch(fehler);
    if (vorwahl === 'enablebanking')
      api('/verbindungen')
        .then((v) => (ebVorhanden = v.some((x: any) => x.art === 'enablebanking')))
        .catch(fehler);
  });
</script>

<div class="px-4">
  <Header titel={quelle ? `${quelle.name} verbinden` : 'Bank verbinden'} gross={false} zurueckZu="#/konto-neu" />

  {#if !bank}
    <p class="mb-4 mt-3 text-[15px] text-muted">
      Wähle deine Bank. BankPocket ruft deine Umsätze danach automatisch ab – viermal am Tag, direkt bei der Bank,
      ohne Umweg über fremde Server.
    </p>
    <div class="relative mb-3">
      <Search size={20} class="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-faint" />
      <input
        bind:this={sucheFeld}
        class="feld pl-12"
        placeholder="Name, Ort, BLZ oder IBAN"
        autocapitalize="off"
        spellcheck="false"
        autocomplete="off"
        value={suche}
        oninput={(e) => suchen(e.currentTarget.value)}
      />
    </div>

    {#if suche.trim().length >= 2}
      {#if treffer.length}
        <div class="karte overflow-hidden">
          {#each treffer as t (t.blz)}
            <button class="zeile" onclick={() => waehlen(t)}>
              <BankAvatar quelle={t.familie} name={t.name} />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-[17px]">{t.name}</span>
                <span class="text-[13px] text-muted">{t.ort ? `${t.ort} · ` : ''}BLZ {t.blz}</span>
              </span>
              <ChevronRight size={20} class="text-faint" />
            </button>
          {/each}
        </div>
      {:else}
        <p class="px-1 py-3 text-[14px] text-muted">Keine Bank gefunden. Tipp: Die BLZ steht in deiner IBAN an Stelle 5–12.</p>
      {/if}
    {:else}
      <div class="mb-5 flex flex-wrap gap-2">
        {#each SCHNELLWAHL as w (w.label)}
          <button class="rounded-full bg-card px-3.5 py-2 text-[14px] font-medium" onclick={() => schnellwahl(w.q)}>{w.label}</button>
        {/each}
      </div>
      <div class="karte overflow-hidden">
        {#each banken as b (b.id)}
          <button class="zeile" onclick={() => (bank = b)}>
            <BankAvatar quelle={b.id} name={b.name} />
            <span class="flex-1"><span class="block text-[17px]">{b.name}</span><span class="text-[13px] text-muted">FinTS · BLZ {b.blz}</span></span>
            <ChevronRight size={20} class="text-faint" />
          </button>
        {/each}
      </div>
    {/if}
    <button class="mt-4 px-1 text-[14px] font-medium text-accent" onclick={() => (bank = { id: 'andere', name: 'Andere Bank' })}>
      Bank nicht dabei? Mit BLZ und FinTS-Adresse verbinden
    </button>
  {:else}
    <div class="mb-6 mt-3 flex items-center gap-4">
      <BankAvatar quelle={bank.art === 'enablebanking' ? ebBank : (bank.art ?? familie)} name={bank.name} groesse={56} />
      <div class="min-w-0">
        <div class="text-[24px] font-bold leading-tight tracking-tight">{bank.name}</div>
        {#if bank.art}
          <a href="#/konto-neu" class="text-[14px] font-medium text-accent">Andere Quelle wählen</a>
        {:else}
          <button class="text-[14px] font-medium text-accent" onclick={() => (bank = null)}>Andere Bank wählen</button>
        {/if}
      </div>
    </div>

    {#if quelle?.anleitung.length}
      <ol class="karte mb-5 space-y-2.5 p-4 text-[14px] leading-relaxed text-muted">
        {#each mitnutzen ? EB_WEITERE : quelle.anleitung as schritt, i (i)}
          <li class="flex gap-3"><span class="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-[12px] font-bold text-accent">{i + 1}</span><span>{schritt}</span></li>
        {/each}
      </ol>
    {/if}

    <form class="space-y-4" onsubmit={verbinden} autocomplete="off">
      {#if bank.id === 'andere' && !bank.blz}
        <div><label class="label" for="v-blz">Bankleitzahl</label><input id="v-blz" class="feld" inputmode="numeric" bind:value={blz} /></div>
        <div>
          <label class="label" for="v-url">FinTS-Adresse</label>
          <input id="v-url" class="feld" placeholder="https://…" autocapitalize="off" spellcheck="false" bind:value={url} />
        </div>
      {/if}
      {#if !mitnutzen && (!quelle || quelle.login)}
        <div>
          <label class="label" for="v-login">{quelle?.login ?? LOGIN_LABEL[familie] ?? 'Anmeldename / Kundennummer'}</label>
          <input
            id="v-login"
            class="feld"
            type={quelle?.loginModus === 'tel' ? 'tel' : 'text'}
            placeholder={quelle?.loginPlatzhalter ?? ''}
            autocapitalize="off"
            spellcheck="false"
            autocomplete="off"
            bind:value={login}
          />
        </div>
      {/if}
      {#if quelle?.redirect && !mitnutzen}
        <div>
          <span class="label">Redirect-URL (bei Enable Banking eintragen)</span>
          <div class="feld select-all break-all text-[14px]">{redirectUrl}</div>
        </div>
      {/if}
      {#if !mitnutzen}
      <div>
        <label class="label" for="v-pin">{quelle?.pin ?? 'PIN'}</label>
        {#if quelle?.pinMehrzeilig}
          <textarea id="v-pin" class="feld min-h-36 font-mono text-[12px]" autocomplete="off" spellcheck="false" placeholder="-----BEGIN PRIVATE KEY-----" bind:value={pin}></textarea>
        {:else}
        <div class="relative">
          <input
            id="v-pin"
            class="feld pr-12"
            type={zeigen ? 'text' : 'password'}
            inputmode={quelle?.pinModus === 'numeric' ? 'numeric' : undefined}
            autocomplete="off"
            spellcheck="false"
            bind:value={pin}
          />
          <button type="button" class="absolute right-2 top-1/2 grid size-10 -translate-y-1/2 place-items-center text-muted" onclick={() => (zeigen = !zeigen)} aria-label="Eingabe zeigen">
            {#if zeigen}<EyeOff size={20} />{:else}<Eye size={20} />{/if}
          </button>
        </div>
        {/if}
      </div>
      {/if}
      <div class="flex gap-3 rounded-2xl bg-card p-4 text-[13px] leading-relaxed text-muted">
        <ShieldCheck size={22} class="shrink-0 text-accent" />
        <p>
          {#if quelle}{quelle.hinweis} Deine Zugangsdaten werden verschlüsselt auf deinem Server gespeichert.
          {:else}Deine Zugangsdaten werden verschlüsselt auf deinem Server gespeichert und nur an {bank.name} gesendet.
            Gleich bestätigst du den Zugriff einmal in deiner {FREIGABE_APP[familie] ?? 'Banking-App'} – danach etwa alle 90 Tage erneut.{/if}
        </p>
      </div>
      <button class="knopf-primaer w-full" disabled={!bereit || sendet}>Verbinden</button>
    </form>
  {/if}
</div>
