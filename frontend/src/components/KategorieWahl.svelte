<script lang="ts">
  // Kategorie auswählen durch Eintippen: Die Liste filtert mit, eine fehlende Kategorie lässt sich direkt anlegen.
  import { ChevronDown, Plus } from '@lucide/svelte';
  import { emoji, oberVon } from '../lib/kategorien';

  let {
    id = 'kategorie',
    wert,
    optionen,
    platzhalter = 'Kategorie wählen',
    onwahl,
    onneu,
  }: {
    id?: string;
    wert: string | null;
    optionen: string[];
    platzhalter?: string;
    onwahl: (kategorie: string) => void;
    onneu?: (name: string) => void;
  } = $props();

  let offen = $state(false);
  let text = $state('');
  let feld = $state<HTMLInputElement>();

  const gesucht = $derived(text.trim().toLowerCase());
  // die Suche trifft auch über die Oberkategorie: „lebens“ zeigt Lebensmittel samt Unterkategorien
  const treffer = $derived(gesucht ? optionen.filter((k) => k.toLowerCase().includes(gesucht) || oberVon[k]?.toLowerCase().includes(gesucht)) : optionen);
  const gibtEs = $derived(optionen.some((k) => k.toLowerCase() === gesucht));

  function oeffnen() {
    offen = true;
    text = '';
    setTimeout(() => feld?.focus(), 0);
  }

  function waehlen(k: string) {
    offen = false;
    onwahl(k);
  }

  function bestaetigen(e: SubmitEvent) {
    e.preventDefault();
    if (treffer.length === 1 || (treffer.length && gibtEs)) waehlen(treffer.find((k) => k.toLowerCase() === gesucht) ?? treffer[0]);
    else if (!treffer.length && gesucht && onneu) neu();
  }

  function neu() {
    offen = false;
    onneu?.(text.trim());
  }
</script>

{#if !offen}
  <button {id} type="button" class="feld flex items-center justify-between text-left" onclick={oeffnen} aria-haspopup="listbox">
    <span class={wert ? '' : 'text-faint'}>{wert ? `${emoji(wert)}  ${wert}` : platzhalter}{#if wert && oberVon[wert]}<span class="text-[13px] text-faint"> · {oberVon[wert]}</span>{/if}</span>
    <ChevronDown size={18} class="shrink-0 text-faint" />
  </button>
{:else}
  <form onsubmit={bestaetigen}>
    <input
      {id}
      bind:this={feld}
      class="feld"
      placeholder="Kategorie eintippen …"
      autocomplete="off"
      autocapitalize="sentences"
      maxlength="40"
      bind:value={text}
      onkeydown={(e) => e.key === 'Escape' && (offen = false)}
    />
  </form>
  <div class="karte mt-1.5 max-h-60 overflow-y-auto" role="listbox">
    {#each treffer as k (k)}
      <button
        type="button"
        class="flex w-full items-center gap-2 py-2.5 pr-4 text-left text-[15px] active:bg-card-hi {oberVon[k] ? 'pl-9' : 'pl-4'} {k === wert ? 'font-semibold text-accent' : ''}"
        role="option"
        aria-selected={k === wert}
        onclick={() => waehlen(k)}>{emoji(k)}  {k}{#if oberVon[k] && gesucht}<span class="text-[12px] font-normal text-faint">in {oberVon[k]}</span>{/if}</button
      >
    {/each}
    {#if onneu && gesucht && !gibtEs}
      <button type="button" class="flex w-full items-center gap-2 border-t border-line px-4 py-2.5 text-left text-[15px] text-accent" onclick={neu}>
        <Plus size={17} /> „{text.trim()}“ als neue Kategorie anlegen
      </button>
    {:else if !treffer.length}
      <div class="px-4 py-3 text-[14px] text-muted">Keine Kategorie gefunden.</div>
    {/if}
  </div>
{/if}
