<script lang="ts">
  import { fly } from 'svelte/transition';
  import { ui } from '../lib/store.svelte';
</script>

{#if ui.toast}
  <div
    class="pointer-events-none fixed inset-x-0 z-[60] flex justify-center px-4"
    style="bottom: calc(env(safe-area-inset-bottom) + 92px)"
    transition:fly={{ y: 24, duration: 220 }}
  >
    <div
      class="max-w-[440px] rounded-2xl px-4 py-3 text-[15px] font-medium shadow-2xl shadow-black {ui.toast.art === 'fehler'
        ? 'bg-neg-soft text-neg'
        : 'bg-card-hi text-text'}"
      role="status"
    >
      {ui.toast.text}
    </div>
  </div>
{/if}
