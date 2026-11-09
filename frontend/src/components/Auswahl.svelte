<script lang="ts" generics="T extends string | number">
  // Auswahl per Knopf statt Tippen: ein paar übliche Werte, auf Wunsch „Andere“ mit Eingabefeld
  let {
    optionen,
    wert = $bindable(),
    andere = false,
    einheit = '',
    platzhalter = '',
    onwahl,
  }: { optionen: [T, string][]; wert: T; andere?: boolean; einheit?: string; platzhalter?: string; onwahl?: (w: T) => void } = $props();

  const bekannt = $derived(optionen.some(([w]) => w === wert));
  let frei = $state(false);
  const offen = $derived(andere && (frei || (!bekannt && wert !== '' && wert !== null && wert !== undefined)));

  function waehlen(w: T) {
    frei = false;
    wert = w;
    onwahl?.(w);
  }
</script>

<div class="flex flex-wrap gap-1.5">
  {#each optionen as [w, label] (w)}
    <button
      type="button"
      class="rounded-full px-3.5 py-2 text-[14px] font-semibold transition-colors {!offen && wert === w ? 'bg-accent text-white' : 'bg-card-hi text-muted'}"
      aria-pressed={!offen && wert === w}
      onclick={() => waehlen(w)}>{label}</button
    >
  {/each}
  {#if andere}
    <button type="button" class="rounded-full px-3.5 py-2 text-[14px] font-semibold {offen ? 'bg-accent text-white' : 'bg-card-hi text-muted'}" aria-pressed={offen} onclick={() => (frei = true)}>Andere</button>
  {/if}
</div>
{#if offen}
  <div class="relative mt-2">
    <input class="feld {einheit ? 'pr-16' : ''}" inputmode={typeof optionen[0]?.[0] === 'number' ? 'numeric' : 'text'} placeholder={platzhalter} value={bekannt ? '' : wert}
      oninput={(e) => { const v = e.currentTarget.value; wert = (typeof optionen[0]?.[0] === 'number' ? Number(v.replace(',', '.')) || 0 : v) as T; onwahl?.(wert); }} />
    {#if einheit}<span class="absolute right-4 top-1/2 -translate-y-1/2 text-muted">{einheit}</span>{/if}
  </div>
{/if}
