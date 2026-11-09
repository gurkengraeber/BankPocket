<script lang="ts">
  import { CircleAlert, CircleCheck, ExternalLink, LoaderCircle, Smartphone } from '@lucide/svelte';
  import { api } from '../lib/api';
  import { fehler } from '../lib/store.svelte';
  import Amount from './Amount.svelte';

  let { v, onschliessen }: { v: any; onschliessen?: () => void } = $props();

  let tan = $state('');
  let rueckkehr = $state('');
  let sendet = $state(false);
  const live = $derived(v.live ?? { phase: 'start', text: '' });
  const app = $derived(
    v.bank === 'ing' ? 'ING-App' : v.bank === 'consorsbank' ? 'SecurePlus-App' : v.art === 'trade_republic' ? 'Trade-Republic-App' : 'Banking-App',
  );
  const istLogin = $derived(v.art === 'trade_republic');

  async function senden(daten: Record<string, unknown>) {
    sendet = true;
    try {
      await api(`/verbindungen/${v.id}/eingabe`, { body: daten });
    } catch (e) {
      fehler(e);
    } finally {
      sendet = false;
    }
  }

  async function abbrechen() {
    await api(`/verbindungen/${v.id}/abbrechen`, { method: 'POST' }).catch(fehler);
  }
</script>

<div class="flex flex-col items-center px-2 py-4 text-center">
  {#if live.phase === 'freigabe'}
    <div class="relative mb-8 mt-4 size-24">
      <span class="puls absolute inset-0 rounded-full"></span>
      <span class="relative grid size-24 place-items-center rounded-full bg-accent text-accent-ink"><Smartphone size={42} /></span>
    </div>
    <h2 class="text-[24px] font-bold tracking-tight">{istLogin ? 'Anmeldung bestätigen' : `Freigabe in der ${app}`}</h2>
    <p class="mt-3 max-w-sm text-[15px] text-muted">{live.text}</p>
    <p class="mt-4 max-w-sm text-[13px] text-faint">
      {istLogin
        ? `Öffne die ${app} und bestätige die Anmeldung von BankPocket.`
        : `${v.name} fragt, ob BankPocket deine Umsätze lesen darf.`} Sobald du bestätigst, geht es hier automatisch weiter.
    </p>
    {#if live.manuell_bestaetigen}
      <button class="knopf-primaer mt-7 w-full" disabled={sendet} onclick={() => senden({ bestaetigt: true })}>
        Ich habe freigegeben
      </button>
    {/if}
    <button class="mt-5 text-[15px] font-medium text-muted" onclick={abbrechen}>Abbrechen</button>
  {:else if live.phase === 'link'}
    <h2 class="text-[24px] font-bold tracking-tight">Zugriff bei der Bank freigeben</h2>
    <p class="mt-3 max-w-sm text-[15px] text-muted">{live.text}</p>
    <!-- nur echte https-Adressen der Bank öffnen -->
    <a class="knopf-primaer mt-6 w-full" href={String(live.url).startsWith('https://') ? live.url : undefined} target="_blank" rel="noopener noreferrer">
      <ExternalLink size={18} />Link öffnen
    </a>
    <p class="mt-4 max-w-sm text-[13px] text-faint">
      Nach der Freigabe kehrt die Bank zu BankPocket zurück, und es geht hier automatisch weiter. Landest du auf einer
      Fehlerseite („Seite nicht erreichbar“), kopiere die Adresse aus der Adresszeile und füge sie unten ein.
    </p>
    <form class="mt-5 w-full" onsubmit={(e) => { e.preventDefault(); senden({ code: rueckkehr }); }}>
      <input class="feld" placeholder="Adresse oder Code einfügen" autocapitalize="off" spellcheck="false" bind:value={rueckkehr} />
      <button class="knopf-sekundaer mt-3 w-full" disabled={!rueckkehr || sendet}>Weiter</button>
    </form>
    <button class="mt-5 text-[15px] font-medium text-muted" onclick={abbrechen}>Abbrechen</button>
  {:else if live.phase === 'tan'}
    <h2 class="text-[24px] font-bold tracking-tight">{istLogin ? 'Code eingeben' : 'TAN eingeben'}</h2>
    <p class="mt-3 max-w-sm text-[15px] text-muted">{live.text}</p>
    {#if live.bild}<img src={live.bild} alt="TAN-Grafik" class="mt-5 w-56 rounded-xl bg-white p-2" />{/if}
    <form class="mt-6 w-full" onsubmit={(e) => { e.preventDefault(); senden({ tan }); }}>
      <input class="feld text-center text-2xl tracking-[0.3em]" inputmode="numeric" autocomplete="one-time-code" bind:value={tan} placeholder="TAN" />
      <button class="knopf-primaer mt-4 w-full" disabled={!tan || sendet}>Bestätigen</button>
    </form>
    <button class="mt-5 text-[15px] font-medium text-muted" onclick={abbrechen}>Abbrechen</button>
  {:else if live.phase === 'auswahl'}
    <h2 class="text-[24px] font-bold tracking-tight">{live.text}</h2>
    <div class="karte mt-6 w-full overflow-hidden">
      {#each live.optionen ?? [] as o (o.id)}
        <button class="zeile justify-between" disabled={sendet} onclick={() => senden({ [live.feld ?? 'tan_verfahren']: o.id })}>
          <span class="text-[17px]">{o.name}</span>
        </button>
      {/each}
    </div>
    <button class="mt-5 text-[15px] font-medium text-muted" onclick={abbrechen}>Abbrechen</button>
  {:else if live.phase === 'fertig'}
    <span class="mb-5 mt-4 grid size-20 place-items-center rounded-full bg-accent-soft text-accent"><CircleCheck size={44} /></span>
    <h2 class="text-[24px] font-bold tracking-tight">Alles aktuell</h2>
    <p class="mt-2 text-[15px] text-muted">{live.text}</p>
    {#if live.konten?.length}
      <div class="karte mt-6 w-full overflow-hidden text-left">
        {#each live.konten as k (k.id)}
          <div class="zeile">
            <div class="min-w-0 flex-1">
              <div class="truncate text-[17px]">{k.name}</div>
              <div class="text-[13px] text-muted">{k.gruppe}{k.neu ? ' · neu' : ''}</div>
            </div>
            <Amount wert={k.saldo} farbig klasse="text-[17px] font-medium" />
          </div>
        {/each}
      </div>
    {/if}
    {#if onschliessen}<button class="knopf-primaer mt-7 w-full" onclick={onschliessen}>Fertig</button>{/if}
  {:else if live.phase === 'fehler'}
    <span class="mb-5 mt-4 grid size-20 place-items-center rounded-full bg-neg-soft text-neg"><CircleAlert size={44} /></span>
    <h2 class="text-[24px] font-bold tracking-tight">Das hat nicht geklappt</h2>
    <p class="mt-3 max-w-sm text-[15px] text-muted">{live.text}</p>
    {#if onschliessen}<button class="knopf-sekundaer mt-7 w-full" onclick={onschliessen}>Schließen</button>{/if}
  {:else}
    <LoaderCircle class="mb-5 mt-8 animate-spin text-accent" size={44} />
    <p class="text-[17px] font-medium">{live.text || 'Verbinde …'}</p>
    <p class="mt-2 text-[13px] text-faint">{v.name}</p>
  {/if}
</div>
