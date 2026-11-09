<script lang="ts">
  import { LoaderCircle } from '@lucide/svelte';

  // Platzhalter, solange Daten laden: Das Gerüst der Seite steht sofort, über den grauen Balken läuft ein Schimmer.
  // form: seite (Kennzahl-Karte + Liste), liste (nur Zeilen), kacheln (vier Kacheln + Karte), detail (Kopf + Zeilen),
  //       block (Balken ohne Karte, für das Innere einer Karte), kreis (der alte Ladekreis, mit Text)
  type Form = 'seite' | 'liste' | 'kacheln' | 'detail' | 'block' | 'kreis';
  let { text = '', form = 'seite', zeilen = 5 }: { text?: string; form?: Form; zeilen?: number } = $props();
  const breiten = ['w-2/3', 'w-1/2', 'w-3/5', 'w-2/5', 'w-1/2', 'w-3/4', 'w-2/5'];
</script>

{#snippet liste(n: number)}
  <div class="karte overflow-hidden">
    {#each Array(n) as _, i (i)}
      <div class="zeile">
        <span class="schimmer size-10 shrink-0 rounded-[14px]"></span>
        <span class="min-w-0 flex-1 space-y-2">
          <span class="schimmer block h-3.5 rounded-full {breiten[i % breiten.length]}"></span>
          <span class="schimmer block h-2.5 w-1/3 rounded-full"></span>
        </span>
        <span class="schimmer h-3.5 w-14 shrink-0 rounded-full"></span>
      </div>
    {/each}
  </div>
{/snippet}

{#snippet kennzahl()}
  <div class="space-y-3">
    <span class="schimmer block h-3.5 w-1/3 rounded-full"></span>
    <span class="schimmer block h-8 w-1/2 rounded-full"></span>
    <span class="schimmer block h-3 w-2/3 rounded-full"></span>
  </div>
{/snippet}

{#if form === 'kreis' || text}
  <div class="flex flex-col items-center gap-3 py-16 text-muted">
    <LoaderCircle class="animate-spin text-accent" size={30} />
    {#if text}<p class="text-sm">{text}</p>{/if}
  </div>
{:else}
  <div aria-busy="true" aria-label="Lädt …" role="status">
    {#if form === 'block'}
      {@render kennzahl()}
      <span class="schimmer mt-6 block h-32 rounded-2xl"></span>
    {:else if form === 'liste'}
      {@render liste(zeilen)}
    {:else if form === 'kacheln'}
      <div class="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {#each Array(4) as _, i (i)}
          <div class="karte space-y-2.5 p-3.5">
            <span class="schimmer block h-3 w-1/2 rounded-full"></span>
            <span class="schimmer block h-5 w-2/3 rounded-full"></span>
            <span class="schimmer block h-2.5 w-3/4 rounded-full"></span>
          </div>
        {/each}
      </div>
      <div class="karte mt-5 p-5">{@render kennzahl()}<span class="schimmer mt-6 block h-32 rounded-2xl"></span></div>
    {:else if form === 'detail'}
      <div class="flex flex-col items-center gap-3 pb-2 pt-3">
        <span class="schimmer size-[72px] rounded-[20px]"></span>
        <span class="schimmer h-5 w-1/2 rounded-full"></span>
        <span class="schimmer h-9 w-2/5 rounded-full"></span>
        <span class="schimmer h-3 w-1/4 rounded-full"></span>
      </div>
      <div class="mt-6">{@render liste(3)}</div>
      <span class="schimmer mb-3 mt-7 block h-4 w-1/3 rounded-full"></span>
      {@render liste(zeilen)}
    {:else}
      <div class="karte p-5">{@render kennzahl()}</div>
      <span class="schimmer mb-3 mt-7 block h-4 w-1/3 rounded-full"></span>
      {@render liste(zeilen)}
    {/if}
  </div>
{/if}
