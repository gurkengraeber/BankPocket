<script lang="ts">
  import { ChevronRight, KeyRound, RefreshCw } from '@lucide/svelte';
  import { onMount, untrack } from 'svelte';
  import AbrufStatus from '../components/AbrufStatus.svelte';
  import BankAvatar from '../components/BankAvatar.svelte';
  import Header from '../components/Header.svelte';
  import Laden from '../components/Laden.svelte';
  import Sheet from '../components/Sheet.svelte';
  import { api } from '../lib/api';
  import { datum, zeitpunkt } from '../lib/format';
  import { gehe } from '../lib/router.svelte';
  import { fehler, toast } from '../lib/store.svelte';

  let { id, neu = false }: { id: number; neu?: boolean } = $props();

  const STATUS: Record<string, [string, string]> = {
    ok: ['Verbunden', 'bg-accent-soft text-pos'],
    neu: ['Bereit', 'bg-card-hi text-muted'],
    laeuft: ['Aktualisiert gerade', 'bg-card-hi text-muted'],
    fehler: ['Fehler beim Abruf', 'bg-neg-soft text-neg'],
    freigabe_noetig: ['Freigabe nötig', 'bg-warn-soft text-warn'],
    auswahl_noetig: ['Auswahl nötig', 'bg-warn-soft text-warn'],
    pin_falsch: ['Zugang abgelehnt', 'bg-neg-soft text-neg'],
    gesperrt: ['Zugang gesperrt', 'bg-neg-soft text-neg'],
  };

  let v = $state<any>(null);
  let sahLaufen = $state(untrack(() => neu)); // nur der Startwert zählt
  let ergebnisGesehen = $state(false);
  let zugangOffen = $state(false);
  let neuePin = $state('');
  let neuerLogin = $state('');
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function laden() {
    try {
      v = await api(`/verbindungen/${id}`);
      if (v.live?.laeuft) {
        sahLaufen = true;
        timer = setTimeout(laden, 1000);
      }
    } catch (e) {
      fehler(e);
    }
  }

  async function abrufen() {
    try {
      await api(`/verbindungen/${id}/abrufen`, { method: 'POST' });
      sahLaufen = true;
      ergebnisGesehen = false;
      laden();
    } catch (e) {
      fehler(e);
    }
  }

  async function zugangSpeichern(e: SubmitEvent) {
    e.preventDefault();
    try {
      v = await api(`/verbindungen/${id}`, { method: 'PATCH', body: { pin: neuePin || undefined, login: neuerLogin || undefined } });
      neuePin = neuerLogin = '';
      zugangOffen = false;
      toast('Zugangsdaten gespeichert');
    } catch (err) {
      fehler(err);
    }
  }

  async function entfernen() {
    if (!confirm(`Verbindung zu ${v.name} entfernen? Deine Konten und bisherigen Buchungen bleiben erhalten.`)) return;
    await api(`/verbindungen/${id}`, { method: 'DELETE' }).catch(fehler);
    toast('Verbindung entfernt');
    gehe('/einstellungen');
  }

  const liveAnzeigen = $derived(v?.live && (v.live.laeuft || (sahLaufen && !ergebnisGesehen)));

  onMount(() => {
    laden();
    return () => clearTimeout(timer);
  });
</script>

<div class="px-4">
  <Header titel={v?.name ?? 'Verbindung'} gross={false} zurueckZu="#/einstellungen" />

  {#if !v}
    <Laden form="detail" zeilen={2} />
  {:else if liveAnzeigen}
    <AbrufStatus
      {v}
      onschliessen={() => {
        ergebnisGesehen = true;
        if (neu && v.live.phase === 'fertig') gehe('/');
      }}
    />
  {:else}
    {@const [label, stil] = STATUS[v.status] ?? [v.status, 'bg-card-hi text-muted']}
    <div class="flex flex-col items-center pt-3 text-center">
      <BankAvatar quelle={v.bank} name={v.name} groesse={68} />
      <h1 class="mt-3 text-[26px] font-bold tracking-tight">{v.name}</h1>
      <span class="pill mt-2 {stil}">{label}</span>
    </div>

    {#if v.status === 'freigabe_noetig'}
      <div class="mt-6 rounded-2xl bg-warn-soft p-4 text-[14px] leading-relaxed text-warn">
        {#if v.art === 'trade_republic'}
          Deine Anmeldung bei Trade Republic ist abgelaufen. Tippe auf „Neu anmelden“ und bestätige in der
          Trade-Republic-App.
        {:else}
          Deine Bank möchte, dass du den Zugriff erneut bestätigst (das ist etwa alle 90 Tage nötig). Tippe auf „Jetzt
          freigeben“, wenn du deine Banking-App zur Hand hast.
        {/if}
      </div>
    {:else if v.meldung && v.status !== 'ok'}
      <div class="mt-6 rounded-2xl {v.status === 'neu' ? 'bg-card text-muted' : 'bg-neg-soft text-neg'} p-4 text-[14px] leading-relaxed">{v.meldung}</div>
    {/if}

    <div class="karte mt-6 divide-y divide-line text-[16px]">
      <div class="flex justify-between gap-4 px-4 py-3.5"><span class="text-muted">Zuletzt aktualisiert</span><span>{zeitpunkt(v.letzter_erfolg)}</span></div>
      {#if v.freigabe_faellig_am}
        {@const faellig = new Date(`${v.freigabe_faellig_am}T23:59:59`) < new Date()}
        <div class="flex justify-between gap-4 px-4 py-3.5">
          <span class="text-muted">Nächste Freigabe</span>
          <span class={faellig ? 'text-warn' : ''}>{faellig ? 'jetzt fällig' : `ca. ${datum(v.freigabe_faellig_am)}`}</span>
        </div>
      {/if}
      {#if v.art === 'fints'}
        <div class="flex justify-between gap-4 px-4 py-3.5"><span class="text-muted">Verfahren</span><span class="truncate">{v.tan_verfahren ?? '–'}</span></div>
      {/if}
    </div>

    {#if v.konten.length}
      <h2 class="abschnitt">Konten</h2>
      <div class="karte overflow-hidden">
        {#each v.konten as k (k.id)}
          <a class="zeile" href="#/konto/{k.id}">
            <span class="flex-1 text-[17px]">{k.name}</span><span class="text-[14px] text-muted">{k.gruppe}</span>
            <ChevronRight size={18} class="text-faint" />
          </a>
        {/each}
      </div>
    {/if}

    <div class="mt-8 space-y-3">
      {#if v.status === 'pin_falsch' || v.status === 'gesperrt'}
        <button class="knopf-primaer w-full" onclick={() => (zugangOffen = true)}><KeyRound size={18} /> Zugangsdaten prüfen</button>
      {:else}
        <button class="knopf-primaer w-full" onclick={abrufen}>
          <RefreshCw size={18} />{v.status !== 'freigabe_noetig' ? 'Jetzt abrufen' : v.art === 'trade_republic' ? 'Neu anmelden' : 'Jetzt freigeben'}
        </button>
        <button class="knopf-sekundaer w-full" onclick={() => (zugangOffen = true)}>Zugangsdaten ändern</button>
      {/if}
      <button class="knopf-gefahr w-full" onclick={entfernen}>Verbindung entfernen</button>
    </div>
  {/if}
</div>

<Sheet bind:offen={zugangOffen} titel="Zugangsdaten">
  <form class="space-y-4" onsubmit={zugangSpeichern} autocomplete="off">
    <p class="-mt-2 text-[14px] text-muted">Leer lassen, was gleich bleibt. Nach dem Speichern startest du den Abruf neu.</p>
    {#if v?.art !== 'splitwise'}
      <div>
        <label class="label" for="z-login">{v?.art === 'trade_republic' ? 'Handynummer mit Ländervorwahl (+49 …)' : v?.art === 'binance' ? 'API-Key' : v?.art === 'enablebanking' ? 'Application-ID' : 'Login / Zugangsnummer'}</label>
        <input id="z-login" class="feld" autocapitalize="off" bind:value={neuerLogin} />
      </div>
    {/if}
    <div>
      <label class="label" for="z-pin">{v?.art === 'binance' ? 'Secret Key' : v?.art === 'splitwise' ? 'API-Schlüssel' : v?.art === 'enablebanking' ? 'Privater Schlüssel (PEM)' : 'Neue PIN'}</label>
      <input id="z-pin" class="feld" type="password" autocomplete="off" bind:value={neuePin} />
    </div>
    <button class="knopf-primaer w-full" disabled={!neuePin && !neuerLogin}>Speichern</button>
  </form>
</Sheet>
