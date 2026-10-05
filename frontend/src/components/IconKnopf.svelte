<script lang="ts">
  import type { Snippet } from 'svelte';
  import Badge from './Badge.svelte';

  let {
    href,
    onclick,
    label,
    badge = 0,
    children,
  }: { href?: string; onclick?: () => void; label: string; badge?: number; children: Snippet } = $props();
</script>

{#if href}
  <a {href} class="relative grid size-10 place-items-center rounded-full text-accent active:bg-card" aria-label={label}>
    {@render children()}
    {#if badge}<Badge n={badge} />{/if}
  </a>
{:else}
  <button {onclick} class="relative grid size-10 place-items-center rounded-full text-accent active:bg-card" aria-label={label}>
    {@render children()}
    {#if badge}<Badge n={badge} />{/if}
  </button>
{/if}
