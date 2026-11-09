<script lang="ts">
  import { api } from '../lib/api';
  import { auth } from '../lib/store.svelte';

  let passwort = $state('');
  let meldung = $state('');
  let sendet = $state(false);

  async function anmelden(e: SubmitEvent) {
    e.preventDefault();
    sendet = true;
    meldung = '';
    try {
      await api('/login', { body: { passwort } });
      auth.angemeldet = true;
    } catch (err) {
      meldung = err instanceof Error ? err.message : String(err);
    } finally {
      sendet = false;
    }
  }
</script>

<div class="mx-auto flex min-h-dvh max-w-sm flex-col items-center justify-center px-6 pb-16">
  <img src="/icon.svg" alt="" class="size-20 rounded-[24px]" />
  <h1 class="mt-5 text-[30px] font-bold tracking-tight">BankPocket</h1>
  <p class="mt-1 text-[15px] text-muted">Deine Finanzen, auf deinem Server.</p>
  {#if !auth.passwort_gesetzt}
    <div class="karte mt-8 w-full p-5 text-[14px] leading-relaxed text-muted">
      Lege zuerst auf dem Server ein Passwort fest:
      <pre class="mt-3 overflow-x-auto rounded-xl bg-bg p-3 text-[12px] text-text">docker compose exec -u bankpocket bankpocket python -m bankpocket.passwort</pre>
      Ohne Docker, im Ordner von BankPocket:
      <pre class="mt-3 overflow-x-auto rounded-xl bg-bg p-3 text-[12px] text-text">BANKPOCKET_DATA_DIR=$PWD/data .venv/bin/python -m bankpocket.passwort</pre>
      Danach diese Seite neu laden.
    </div>
  {:else}
    <form class="mt-10 w-full space-y-4" onsubmit={anmelden}>
      <input class="feld" type="password" placeholder="Passwort" autocomplete="current-password" bind:value={passwort} />
      {#if meldung}<p class="px-1 text-[14px] text-neg">{meldung}</p>{/if}
      <button class="knopf-primaer w-full" disabled={!passwort || sendet}>Anmelden</button>
    </form>
  {/if}
</div>
