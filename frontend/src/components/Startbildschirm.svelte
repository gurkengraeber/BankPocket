<script lang="ts">
  import { SquarePlus, X } from '@lucide/svelte';
  import { installation } from '../lib/installieren.svelte';
  import { merker } from '../lib/store.svelte';
  import Sheet from './Sheet.svelte';

  // hinweis: dezente Leiste über der Tab-Leiste (einmal wegtippen, dann bleibt sie weg) statt eines Knopfs
  let { klasse = '', hinweis = false }: { klasse?: string; hinweis?: boolean } = $props();
  let anleitungOffen = $state(false);
  let weg = $state(merker.lesen('bp_startbildschirm_weg') === '1');

  function ausblenden() {
    weg = true;
    merker.schreiben('bp_startbildschirm_weg', '1');
  }

  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const firefox = /firefox|fxios/i.test(navigator.userAgent);
  const sicher = window.isSecureContext;

  async function hinzufuegen() {
    if (!installation.ereignis) {
      anleitungOffen = true;
      return;
    }
    installation.ereignis.prompt();
    await installation.ereignis.userChoice.catch(() => {});
    installation.ereignis = null;
  }
</script>

{#if !installation.installiert}
  {#if !hinweis}
    <button class="pill-accent !rounded-2xl !px-5 !py-3 text-[16px] font-semibold lg:hidden {klasse}" onclick={hinzufuegen}>
      <SquarePlus size={20} /> Zum Startbildschirm
    </button>
  {:else if !weg}
    <div
      class="fixed inset-x-3 z-30 mx-auto flex max-w-[456px] items-center gap-1 rounded-2xl border border-line bg-card/95 py-1.5 pl-3.5 pr-1.5 text-[13px] shadow-lg backdrop-blur-xl lg:hidden"
      style="bottom: calc(env(safe-area-inset-bottom) + 5.25rem)"
    >
      <button class="flex min-w-0 flex-1 items-center gap-2.5 py-1.5 text-left" onclick={hinzufuegen}>
        <SquarePlus size={18} class="shrink-0 text-accent" />
        <span class="truncate text-muted">Als App auf den <span class="font-semibold text-text">Startbildschirm</span></span>
      </button>
      <button class="grid size-9 shrink-0 place-items-center rounded-full text-faint active:bg-card-hi" onclick={ausblenden} aria-label="Hinweis ausblenden">
        <X size={17} />
      </button>
    </div>
  {/if}

  <Sheet bind:offen={anleitungOffen} titel="Zum Startbildschirm hinzufügen">
    <ol class="space-y-3 pb-2 text-[15px]">
      {#each ios
        ? ['Tippe unten in Safari auf „Teilen“ (das Quadrat mit dem Pfeil nach oben).', 'Wähle „Zum Home-Bildschirm“.', 'Bestätige mit „Hinzufügen“.']
        : firefox
          ? ['Tippe auf das Menü (⋮) neben der Adresszeile.', 'Wähle „Zum Startbildschirm hinzufügen“.', 'Bestätige mit „Hinzufügen“.']
          : ['Tippe oben rechts auf das Menü (⋮).', 'Wähle „Zum Startbildschirm hinzufügen“ bzw. „App installieren“.', 'Bestätige mit „Hinzufügen“.'] as schritt, i (i)}
        <li class="flex gap-3">
          <span class="grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-[12px] font-bold text-accent">{i + 1}</span>
          <span>{schritt}</span>
        </li>
      {/each}
    </ol>
    <p class="mt-3 text-[13px] leading-relaxed text-muted">
      {#if sicher}
        BankPocket liegt danach wie eine App auf deinem Startbildschirm.
      {:else}
        Dein Server ist gerade nur über http erreichbar. Browser erlauben eine echte App-Installation (eigenes Fenster,
        Push) nur über https – bis dahin entsteht eine Verknüpfung, die BankPocket im Browser öffnet.
      {/if}
    </p>
  </Sheet>
{/if}
