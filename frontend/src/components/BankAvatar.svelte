<script lang="ts">
  import { bankKachel, bankLogo } from '../lib/kategorien';

  let { quelle, name = '', groesse = 44 }: { quelle: string; name?: string; groesse?: number } = $props();
  const k = $derived(bankKachel(quelle, name));
  const emoji = $derived(/\p{Extended_Pictographic}/u.test(k.text));
  // Logo der Bank, falls bekannt – sonst (oder wenn es nicht lädt) die farbige Kachel mit Kürzel
  const logo = $derived(bankLogo(quelle, name));
  let logoFehlt = $state(false);
  $effect(() => {
    logo;
    logoFehlt = false;
  });
</script>

{#if logo && !logoFehlt}
  <div
    class="grid shrink-0 place-items-center overflow-hidden rounded-[14px] border border-line bg-white"
    style="width:{groesse}px;height:{groesse}px"
    aria-hidden="true"
  >
    <img src="/api/logo/{logo}" alt="" loading="lazy" class="size-[68%] object-contain" onerror={() => (logoFehlt = true)} />
  </div>
{:else}
  <div
    class="grid shrink-0 place-items-center rounded-[14px] font-extrabold tracking-tight"
    style="width:{groesse}px;height:{groesse}px;background:{k.bg};color:{k.fg};font-size:{emoji
      ? groesse * 0.5
      : k.text.length > 2
        ? groesse * 0.3
        : groesse * 0.4}px"
    aria-hidden="true"
  >
    {k.text}
  </div>
{/if}
