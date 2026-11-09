<script lang="ts">
  import { onMount } from 'svelte';
  import TabBar from './components/TabBar.svelte';
  import Toast from './components/Toast.svelte';
  import { api } from './lib/api';
  import { kategorienMerken } from './lib/kategorien';
  import { route } from './lib/router.svelte';
  import { auth } from './lib/store.svelte';
  import Analysen from './pages/Analysen.svelte';
  import Bereich from './pages/Bereich.svelte';
  import Gehalt from './pages/Gehalt.svelte';
  import Sparen from './pages/Sparen.svelte';
  import Versicherungen from './pages/Versicherungen.svelte';
  import Buchungen from './pages/Buchungen.svelte';
  import Budgets from './pages/Budgets.svelte';
  import Einstellungen from './pages/Einstellungen.svelte';
  import Hinweise from './pages/Hinweise.svelte';
  import Kalender from './pages/Kalender.svelte';
  import Kategorien from './pages/Kategorien.svelte';
  import KontenSortieren from './pages/KontenSortieren.svelte';
  import KontoNeu from './pages/KontoNeu.svelte';
  import Login from './pages/Login.svelte';
  import Uebersicht from './pages/Uebersicht.svelte';
  import Unklar from './pages/Unklar.svelte';
  import Verbinden from './pages/Verbinden.svelte';
  import Verbindung from './pages/Verbindung.svelte';
  import VertragDetail from './pages/VertragDetail.svelte';
  import Vertraege from './pages/Vertraege.svelte';

  onMount(async () => {
    try {
      Object.assign(auth, await api('/auth'));
      if (!auth.aktiv || auth.angemeldet) kategorienMerken(await api('/kategorien'));
    } catch {
      auth.angemeldet = false;
    }
    auth.geprueft = true;
    // Klick auf eine Push-Benachrichtigung: der Service Worker schickt das Ziel
    navigator.serviceWorker?.addEventListener('message', (e) => {
      if (typeof e.data?.navigate === 'string') location.hash = e.data.navigate || '#/';
    });
  });

  const seite = $derived(route.teile[0] ?? '');
  const tab = $derived(seite === 'versicherungen' ? 'versicherungen' : ['vertraege', 'vertrag', 'kalender'].includes(seite) ? 'vertraege' : ['analysen', 'unklar', 'bereich'].includes(seite) ? 'analysen' : seite === 'sparen' ? 'sparen' : 'uebersicht');
  const ohneTabs = $derived(['verbinden', 'verbindung', 'konto-neu'].includes(seite));
  // Am PC nutzen diese Seiten die volle Breite mit Kacheln nebeneinander; alle anderen bleiben eine schmale Spalte
  const breit = $derived(['', 'vertraege', 'analysen', 'unklar', 'sparen', 'versicherungen'].includes(seite));
</script>

{#if !auth.geprueft}
  <div class="grid min-h-dvh place-items-center"><img src="/icon.svg" alt="" class="size-16 animate-pulse rounded-2xl" /></div>
{:else if auth.aktiv && !auth.angemeldet}
  <Login />
{:else}
  <div class="lg:pl-60">
  <main class="mx-auto min-h-dvh max-w-[480px] pb-32 lg:pb-12 lg:pt-4 {breit ? 'lg:max-w-[1080px]' : 'lg:max-w-[600px]'}">
    {#key route.pfad}
      {#if seite === 'vertraege'}<Vertraege />
      {:else if seite === 'vertrag'}<VertragDetail id={Number(route.teile[1])} />
      {:else if seite === 'analysen'}<Analysen />
      {:else if seite === 'sparen'}<Sparen />
      {:else if seite === 'gehalt'}<Gehalt />
      {:else if seite === 'bereich'}<Bereich id={Number(route.teile[1])} />
      {:else if seite === 'versicherungen'}<Versicherungen />
      {:else if seite === 'konto'}<Buchungen konto={Number(route.teile[1])} />
      {:else if seite === 'gruppe'}<Buchungen gruppe={route.teile[1]} />
      {:else if seite === 'verbinden'}<Verbinden />
      {:else if seite === 'verbindung'}<Verbindung id={Number(route.teile[1])} neu={route.query.get('neu') === '1'} />
      {:else if seite === 'einstellungen'}<Einstellungen />
      {:else if seite === 'hinweise'}<Hinweise />
      {:else if seite === 'budgets'}<Budgets />
      {:else if seite === 'kalender'}<Kalender />
      {:else if seite === 'kategorien'}<Kategorien />
      {:else if seite === 'unklar'}<Unklar />
      {:else if seite === 'konten-sortieren'}<KontenSortieren />
      {:else if seite === 'konto-neu'}<KontoNeu />
      {:else}<Uebersicht />{/if}
    {/key}
  </main>
  </div>
  <TabBar aktiv={tab} nurBreit={ohneTabs} />
{/if}
<Toast />
