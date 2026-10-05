<script lang="ts">
  import { Bell, CircleAlert, Hourglass, Smartphone, Sparkles, TrendingUp, TriangleAlert } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Header from '../components/Header.svelte';
  import Laden from '../components/Laden.svelte';
  import { api } from '../lib/api';
  import { vorZeit } from '../lib/format';
  import { fehler } from '../lib/store.svelte';

  const ICONS: Record<string, [any, string]> = {
    freigabe: [Smartphone, 'text-accent bg-accent-soft'],
    freigabe_noetig: [TriangleAlert, 'text-warn bg-warn-soft'],
    auswahl_noetig: [TriangleAlert, 'text-warn bg-warn-soft'],
    pin_falsch: [CircleAlert, 'text-neg bg-neg-soft'],
    gesperrt: [CircleAlert, 'text-neg bg-neg-soft'],
    fehler: [CircleAlert, 'text-neg bg-neg-soft'],
    neuer_vertrag: [Sparkles, 'text-accent bg-accent-soft'],
    betrag_gestiegen: [TrendingUp, 'text-warn bg-warn-soft'],
    ueberfaellig: [Hourglass, 'text-warn bg-warn-soft'],
    sicherung: [CircleAlert, 'text-neg bg-neg-soft'],
    kuendigen: [Hourglass, 'text-accent bg-accent-soft'],
  };

  let liste = $state<any[] | null>(null);

  onMount(async () => {
    try {
      const geladen: any[] = await api('/hinweise');
      liste = geladen;
      if (geladen.some((h) => !h.gelesen)) api('/hinweise/gelesen', { body: {} }).catch(() => {});
    } catch (e) {
      fehler(e);
    }
  });
</script>

<div class="px-4">
  <Header titel="Hinweise" zurueckZu="#/" />
  {#if !liste}
    <Laden form="liste" />
  {:else if !liste.length}
    <div class="flex flex-col items-center py-20 text-center text-muted">
      <Bell size={36} class="mb-3 text-faint" />
      <p class="text-[15px]">Alles ruhig. Hier landen Freigaben, neue Verträge und Warnungen.</p>
    </div>
  {:else}
    <div class="karte overflow-hidden">
      {#each liste as h (h.id)}
        {@const [Icon, stil] = ICONS[h.art] ?? [Bell, 'text-accent bg-accent-soft']}
        <a class="zeile !items-start" href={h.link || '#/hinweise'}>
          <span class="grid size-10 shrink-0 place-items-center rounded-full {stil}"><Icon size={20} /></span>
          <span class="min-w-0 flex-1">
            <span class="flex items-baseline justify-between gap-3">
              <span class="text-[16px] font-semibold">{h.titel}</span>
              <span class="shrink-0 text-[12px] text-faint">{vorZeit(h.erstellt_am)}</span>
            </span>
            {#if h.text}<span class="mt-0.5 block text-[14px] leading-snug text-muted">{h.text}</span>{/if}
          </span>
          {#if !h.gelesen}<span class="mt-2 size-2.5 shrink-0 rounded-full bg-accent"></span>{/if}
        </a>
      {/each}
    </div>
  {/if}
</div>
