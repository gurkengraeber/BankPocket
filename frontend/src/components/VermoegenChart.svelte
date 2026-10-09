<script lang="ts">
  import { datum, euro } from '../lib/format';
  import { ui } from '../lib/store.svelte';

  type Punkt = { d: string; w: number };
  let { punkte, prognose = [], hoehe = 230 }: { punkte: Punkt[]; prognose?: Punkt[]; hoehe?: number } = $props();

  let breite = $state(340);
  let aktiv = $state<number | null>(null);
  let svg = $state<SVGSVGElement>();

  const pad = { l: 4, r: 62, t: 14, b: 30 };
  const alle = $derived([...punkte, ...prognose.slice(1)]);
  const zeit = (d: string) => new Date(`${d}T12:00:00`).getTime();
  const t0 = $derived(alle.length ? zeit(alle[0].d) : 0);
  const t1 = $derived(alle.length ? zeit(alle[alle.length - 1].d) : 1);
  const x = (d: string) => pad.l + ((zeit(d) - t0) / Math.max(t1 - t0, 1)) * (breite - pad.l - pad.r);

  function schoen(v: number) {
    const e = Math.pow(10, Math.floor(Math.log10(v)));
    const f = v / e;
    return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * e;
  }

  const skala = $derived.by(() => {
    const werte = alle.map((p) => p.w);
    let lo = Math.min(...werte);
    let hi = Math.max(...werte);
    if (!isFinite(lo)) return { lo: 0, hi: 1, ticks: [] as number[] };
    if (hi - lo < 1) {
      lo -= 50;
      hi += 50;
    }
    const schritt = schoen((hi - lo) / 4);
    lo = Math.floor(lo / schritt) * schritt;
    hi = Math.ceil(hi / schritt) * schritt;
    const ticks = [];
    for (let v = lo; v <= hi + schritt / 2; v += schritt) ticks.push(v);
    return { lo, hi, ticks };
  });
  const y = (w: number) => pad.t + (1 - (w - skala.lo) / Math.max(skala.hi - skala.lo, 1)) * (hoehe - pad.t - pad.b);

  const pfad = (ps: Punkt[]) => ps.map((p, i) => `${i ? 'L' : 'M'}${x(p.d).toFixed(1)},${y(p.w).toFixed(1)}`).join('');
  const linie = $derived(pfad(punkte));
  const flaeche = $derived(
    punkte.length
      ? `${linie}L${x(punkte[punkte.length - 1].d).toFixed(1)},${hoehe - pad.b}L${x(punkte[0].d).toFixed(1)},${hoehe - pad.b}Z`
      : '',
  );
  const progLinie = $derived(prognose.length > 1 ? pfad(prognose) : '');

  const monate = $derived.by(() => {
    if (!alle.length) return [] as { d: string; text: string; jahr: boolean }[];
    const start = new Date(t0);
    const ende = new Date(t1);
    const out = [];
    const tage = Math.round((t1 - t0) / 86400000);
    if (tage <= 70) {
      // kurzer Zeitraum: etwa fünf Tagesmarken (z. B. jede Woche) statt eines einzelnen Monatsanfangs
      const schritt = Math.max(1, Math.round(tage / 5));
      for (let d = new Date(ende); d >= start; d.setDate(d.getDate() - schritt)) {
        const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        out.unshift({ d: iso, text: d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }), jahr: false });
      }
      // die letzte Marke säße genau am rechten Rand unter der Wertachse
      if (out.length > 2) out.pop();
      return out;
    }
    const anzahl = (ende.getFullYear() - start.getFullYear()) * 12 + ende.getMonth() - start.getMonth();
    const jeder = anzahl > 14 ? 3 : anzahl > 7 ? 2 : 1;
    for (let m = new Date(start.getFullYear(), start.getMonth() + 1, 1), i = 0; m <= ende; m.setMonth(m.getMonth() + 1), i++) {
      if (i % jeder) continue;
      const d = `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, '0')}-01`;
      out.push({ d, text: m.toLocaleDateString('de-DE', { month: 'narrow' }), jahr: m.getMonth() === 0 });
    }
    return out;
  });

  function bewegen(e: PointerEvent) {
    if (!svg || !alle.length) return;
    const px = e.clientX - svg.getBoundingClientRect().left;
    let best = 0;
    let abstand = Infinity;
    alle.forEach((p, i) => {
      const a = Math.abs(x(p.d) - px);
      if (a < abstand) {
        abstand = a;
        best = i;
      }
    });
    aktiv = best;
  }

  const aktivPunkt = $derived(aktiv !== null ? alle[aktiv] : null);
  const istPrognose = $derived(aktiv !== null && aktiv >= punkte.length);
</script>

<div bind:clientWidth={breite} class="relative touch-pan-y select-none">
  {#if aktivPunkt}
    <div
      class="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 rounded-xl bg-card-hi px-3 py-1.5 text-center shadow-xl"
      style="left: {Math.min(Math.max(x(aktivPunkt.d), 70), breite - 70)}px"
    >
      <div class="text-[15px] font-semibold tabular-nums {ui.versteckt ? 'versteckt' : ''}">{euro(aktivPunkt.w)}</div>
      <div class="text-[11px] text-muted">{istPrognose ? 'Prognose · ' : ''}{datum(aktivPunkt.d)}</div>
    </div>
  {/if}
  <svg
    bind:this={svg}
    width={breite}
    height={hoehe}
    class="block overflow-visible"
    onpointerdown={bewegen}
    onpointermove={bewegen}
    onpointerleave={() => (aktiv = null)}
    onpointerup={() => setTimeout(() => (aktiv = null), 1500)}
    role="img"
    aria-label="Vermögensentwicklung"
  >
    <defs>
      <linearGradient id="verlauf" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stop-color="var(--color-accent)" stop-opacity="0.38" />
        <stop offset="1" stop-color="var(--color-accent)" stop-opacity="0" />
      </linearGradient>
    </defs>
    {#each skala.ticks as t (t)}
      <line x1={pad.l} x2={breite - pad.r + 6} y1={y(t)} y2={y(t)} stroke="var(--color-line)" stroke-width="1" />
      <text x={breite - 2} y={y(t) + 4} text-anchor="end" class="fill-faint text-[11px] tabular-nums {ui.versteckt ? 'versteckt' : ''}">
        {euro(t, { kurz: true })}
      </text>
    {/each}
    {#each monate as m (m.d)}
      <line x1={x(m.d)} x2={x(m.d)} y1={pad.t} y2={hoehe - pad.b} stroke="var(--color-line)" stroke-dasharray="2 4" />
      <text x={x(m.d)} y={hoehe - 10} text-anchor="middle" class="fill-muted text-[12px]">{m.text}</text>
      {#if m.jahr}<text x={x(m.d)} y={hoehe + 6} text-anchor="middle" class="fill-faint text-[10px]">{m.d.slice(0, 4)}</text>{/if}
    {/each}
    <path d={flaeche} fill="url(#verlauf)" />
    <path d={linie} fill="none" stroke="var(--color-accent)" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" />
    {#if progLinie}
      <path d={progLinie} fill="none" stroke="var(--color-accent)" stroke-width="2" stroke-dasharray="3 5" stroke-linecap="round" opacity="0.7" />
    {/if}
    {#if aktivPunkt}
      <line x1={x(aktivPunkt.d)} x2={x(aktivPunkt.d)} y1={pad.t} y2={hoehe - pad.b} stroke="var(--color-muted)" stroke-width="1" />
      <circle cx={x(aktivPunkt.d)} cy={y(aktivPunkt.w)} r="5.5" fill="var(--color-bg)" stroke="var(--color-accent)" stroke-width="2.5" />
    {/if}
  </svg>
</div>
