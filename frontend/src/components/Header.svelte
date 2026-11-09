<script lang="ts">
  import { ArrowLeft } from '@lucide/svelte';
  import type { Snippet } from 'svelte';
  import { zurueck } from '../lib/router.svelte';

  let {
    titel,
    gross = true,
    zurueckZu = null,
    aktionen,
  }: { titel: string; gross?: boolean; zurueckZu?: string | null; aktionen?: Snippet } = $props();

  let gescrollt = $state(false);
  $effect(() => {
    const pruefen = () => (gescrollt = window.scrollY > (gross ? 46 : 4));
    pruefen();
    window.addEventListener('scroll', pruefen, { passive: true });
    return () => window.removeEventListener('scroll', pruefen);
  });
</script>

<header
  class="sticky top-0 z-30 -mx-4 px-2 transition-colors duration-200 {gescrollt
    ? 'border-b border-line bg-bg/85 backdrop-blur-xl'
    : 'border-b border-transparent bg-bg'}"
  style="padding-top: env(safe-area-inset-top)"
>
  <div class="flex h-14 items-center">
    <div class="flex {aktionen ? 'min-w-[124px]' : 'min-w-12'}">
      {#if zurueckZu !== null}
        <button
          class="grid size-10 place-items-center rounded-full text-accent active:bg-card"
          onclick={() => zurueck(zurueckZu || '#/')}
          aria-label="Zurück"
        >
          <ArrowLeft size={24} />
        </button>
      {/if}
    </div>
    <div
      class="flex-1 truncate text-center text-[17px] font-semibold transition-opacity duration-200 {gescrollt || !gross
        ? 'opacity-100'
        : 'opacity-0'}"
    >
      {titel}
    </div>
    <div class="flex {aktionen ? 'min-w-[124px]' : 'min-w-12'} justify-end gap-0.5">{@render aktionen?.()}</div>
  </div>
</header>
{#if gross}
  <h1 class="pb-4 pt-1 text-[34px] font-bold leading-tight tracking-tight">{titel}</h1>
{/if}
