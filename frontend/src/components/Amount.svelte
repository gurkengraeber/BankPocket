<script lang="ts">
  import { euro } from '../lib/format';
  import { ui } from '../lib/store.svelte';

  let {
    wert,
    vorzeichen = false,
    farbig = false,
    kurz = false,
    klasse = '',
  }: { wert: number | string | null | undefined; vorzeichen?: boolean; farbig?: boolean; kurz?: boolean; klasse?: string } =
    $props();

  const n = $derived(Number(wert ?? 0));
</script>

<span
  class="whitespace-nowrap tabular-nums {klasse} {farbig && n > 0 ? 'text-pos' : ''} {ui.versteckt ? 'versteckt' : ''}"
  aria-label={ui.versteckt ? 'Betrag ausgeblendet' : undefined}
>
  {ui.versteckt ? (kurz ? '0.000 €' : '0.000,00 €') : euro(wert, { vorzeichen, kurz })}
</span>
