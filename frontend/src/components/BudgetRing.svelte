<script lang="ts">
  import { emoji } from '../lib/kategorien';

  let { kategorie, anteil, status, groesse = 58 }: { kategorie: string; anteil: number; status: string; groesse?: number } =
    $props();

  const r = $derived(groesse / 2 - 3.5);
  const umfang = $derived(2 * Math.PI * r);
  const farbe = $derived(
    status === 'ueberschritten' ? 'var(--color-neg)' : status === 'knapp' ? 'var(--color-warn)' : 'var(--color-accent)',
  );
</script>

<div class="relative grid shrink-0 place-items-center" style="width:{groesse}px;height:{groesse}px" title={kategorie}>
  <svg width={groesse} height={groesse} class="absolute inset-0 -rotate-90" aria-hidden="true">
    <circle cx={groesse / 2} cy={groesse / 2} {r} fill="var(--color-card-hi)" stroke="var(--color-line)" stroke-width="4" />
    <circle
      cx={groesse / 2}
      cy={groesse / 2}
      {r}
      fill="none"
      stroke={farbe}
      stroke-width="4"
      stroke-linecap="round"
      stroke-dasharray={umfang}
      stroke-dashoffset={umfang * (1 - Math.min(Math.max(anteil, 0), 1))}
      class="transition-[stroke-dashoffset] duration-700"
    />
  </svg>
  <span class="relative" style="font-size:{groesse * 0.4}px">{emoji(kategorie)}</span>
</div>
