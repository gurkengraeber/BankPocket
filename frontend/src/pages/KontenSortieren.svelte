<script lang="ts">
  import { GripVertical } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import BankAvatar from '../components/BankAvatar.svelte';
  import Header from '../components/Header.svelte';
  import Laden from '../components/Laden.svelte';
  import { api } from '../lib/api';
  import { fehler } from '../lib/store.svelte';

  let gruppen = $state<any[] | null>(null);
  let gezogen = $state<number | null>(null);

  onMount(() => {
    api('/accounts')
      .then((d) => (gruppen = d.gruppen.filter((g: any) => g.konten.length)))
      .catch(fehler);
  });

  // Ziehen am Griff (Maus und Finger); die Reihenfolge gilt je Gruppe und wird beim Loslassen gespeichert
  function ziehenStart(e: PointerEvent, g: any, k: any) {
    e.preventDefault();
    gezogen = k.id;
    const bewegen = (ev: PointerEvent) => {
      const zeilen = [...document.querySelectorAll(`[data-gruppe="${CSS.escape(g.name)}"] [data-konto]`)];
      const von = g.konten.findIndex((x: any) => x.id === k.id);
      let nach = zeilen.findIndex((z) => {
        const r = z.getBoundingClientRect();
        return ev.clientY < r.top + r.height / 2;
      });
      if (nach === -1) nach = zeilen.length - 1;
      else if (nach > von) nach -= 1;
      if (nach !== von) {
        const [konto] = g.konten.splice(von, 1);
        g.konten.splice(nach, 0, konto);
      }
    };
    const ende = () => {
      window.removeEventListener('pointermove', bewegen);
      window.removeEventListener('pointerup', ende);
      window.removeEventListener('pointercancel', ende);
      gezogen = null;
      api('/accounts/reihenfolge', { method: 'PUT', body: { ids: g.konten.map((x: any) => x.id) } }).catch(fehler);
    };
    window.addEventListener('pointermove', bewegen);
    window.addEventListener('pointerup', ende);
    window.addEventListener('pointercancel', ende);
  }
</script>

<div class="px-4">
  <Header titel="Konten sortieren" gross={false} zurueckZu="#/einstellungen" />

  {#if !gruppen}
    <Laden form="liste" />
  {:else}
    <p class="mb-2 mt-3 text-[15px] text-muted">
      Zieh ein Konto am Griff nach oben oder unten. Die Reihenfolge gilt in der Übersicht und wird sofort gespeichert.
    </p>
    {#each gruppen as g (g.name)}
      <h2 class="abschnitt">{g.name}</h2>
      <div class="karte overflow-hidden" data-gruppe={g.name}>
        {#each g.konten as k (k.id)}
          <div class="zeile {gezogen === k.id ? 'relative z-10 bg-card-hi shadow-lg' : ''}" data-konto={k.id}>
            <BankAvatar quelle={k.quelle} name={k.name} groesse={38} />
            <span class="min-w-0 flex-1 truncate text-[16px] {k.aktiv ? '' : 'text-muted'}">{k.name}</span>
            <button
              class="-mr-2 grid size-10 shrink-0 cursor-grab touch-none place-items-center rounded-xl text-muted active:cursor-grabbing active:bg-card-hi"
              aria-label="{k.name} verschieben"
              onpointerdown={(e) => ziehenStart(e, g, k)}
            >
              <GripVertical size={20} />
            </button>
          </div>
        {/each}
      </div>
    {/each}
    <p class="mt-4 px-1 text-[13px] text-faint">
      In eine andere Gruppe verschiebst du ein Konto über den Stift auf seiner Kontoseite. Geschlossene Konten stehen immer am Ende.
    </p>
  {/if}
</div>
