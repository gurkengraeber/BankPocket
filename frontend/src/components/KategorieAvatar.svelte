<script lang="ts">
  import { emoji, farbe } from '../lib/kategorien';

  // logo: Adresse eines bekannten Anbieters (z. B. „congstar.de“) – dann zeigt die Kachel dessen Logo statt des Emojis
  let { kategorie, groesse = 44, rund = false, logo = null }: { kategorie: string | null; groesse?: number; rund?: boolean; logo?: string | null } =
    $props();
  let logoFehlt = $state(false);
  $effect(() => {
    logo; // bei einem anderen Vertrag neu versuchen
    logoFehlt = false;
  });
</script>

{#if logo && !logoFehlt}
  <div
    class="grid shrink-0 place-items-center overflow-hidden border border-line bg-white {rund ? 'rounded-full' : 'rounded-[14px]'}"
    style="width:{groesse}px;height:{groesse}px"
    aria-hidden="true"
  >
    <img src="/api/logo/{logo}" alt="" loading="lazy" class="size-[68%] object-contain" onerror={() => (logoFehlt = true)} />
  </div>
{:else}

<div
  class="grid shrink-0 place-items-center {rund ? 'rounded-full' : 'rounded-[14px]'}"
  style="width:{groesse}px;height:{groesse}px;font-size:{groesse * 0.48}px;background:color-mix(in srgb, {farbe(
    kategorie ?? '',
  )} 18%, var(--color-card))"
  aria-hidden="true"
>
  {emoji(kategorie)}
</div>
{/if}
