<script lang="ts">
  import { ChevronRight, CornerDownRight, Plus, Trash2 } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Header from '../components/Header.svelte';
  import IconKnopf from '../components/IconKnopf.svelte';
  import KategorieAvatar from '../components/KategorieAvatar.svelte';
  import KategorieWahl from '../components/KategorieWahl.svelte';
  import Laden from '../components/Laden.svelte';
  import Sheet from '../components/Sheet.svelte';
  import { api } from '../lib/api';
  import { emoji, kategorienMerken, SYMBOLE } from '../lib/kategorien';
  import { fehler, toast } from '../lib/store.svelte';

  type Typ = 'ausgabe' | 'einnahme';
  let daten = $state<any>(null);
  let gewaehlt = $state<{ name: string; typ: Typ } | null>(null);
  let detailOffen = $state(false);
  let neuOffen = $state(false);
  let stichwort = $state('');
  let name = $state(''); // im Detail: der (neue) Name
  let neuName = $state('');
  let neuEmoji = $state('🏷️');
  let neuTyp = $state<Typ>('ausgabe');
  let neuOber = $state('');
  let symbolFrei = $state('');
  let stand = $state(0); // zählt hoch, wenn Symbole oder Unterkategorien neu geladen sind – die Avatare lesen sie nicht reaktiv

  const eigene = $derived(new Map<string, any>((daten?.eigene ?? []).map((k: any) => [k.name, k])));
  const regelnVon = (n: string) => (daten?.regeln ?? []).filter((r: any) => r.kategorie === n);
  const ober = $derived<Record<string, string>>(daten?.ober ?? {});
  const unterVon = (n: string) => Object.keys(ober).filter((k) => ober[k] === n);
  // als Oberkategorie taugt alles, was selbst keine Unterkategorie ist
  const oberOptionen = (ohne = '') => [...new Set<string>([...(daten?.ausgabe ?? []), ...(daten?.einnahme ?? [])])].filter((k) => !ober[k] && k !== ohne);

  async function laden() {
    try {
      daten = kategorienMerken(await api('/kategorien'));
      stand++;
    } catch (e) {
      fehler(e);
    }
  }

  function oeffnen(n: string, typ: Typ) {
    gewaehlt = { name: n, typ };
    name = n;
    stichwort = '';
    symbolFrei = '';
    detailOffen = true;
  }

  async function aendern(felder: Record<string, string>, meldung: string) {
    try {
      const r = await api(`/kategorien/${encodeURIComponent(gewaehlt!.name)}`, { method: 'PATCH', body: felder });
      gewaehlt = { name: r.name, typ: gewaehlt!.typ };
      name = r.name;
      toast(meldung);
      await laden();
    } catch (e) {
      fehler(e);
    }
  }

  async function regelAnlegen(e: SubmitEvent) {
    e.preventDefault();
    try {
      const r = await api('/regeln', { body: { stichwort, kategorie: gewaehlt!.name, typ: gewaehlt!.typ } });
      toast(`Regel angelegt – ${r.geaendert} ${r.geaendert === 1 ? 'Buchung' : 'Buchungen'} eingeordnet`);
      stichwort = '';
      laden();
    } catch (err) {
      fehler(err);
    }
  }

  async function regelLoeschen(id: number) {
    await api(`/regeln/${id}`, { method: 'DELETE' }).catch(fehler);
    laden();
  }

  function neuOeffnen(unter = '', typ: Typ = 'ausgabe') {
    neuName = '';
    neuEmoji = '🏷️';
    neuOber = unter;
    neuTyp = typ;
    detailOffen = false;
    neuOffen = true;
  }

  async function kategorieAnlegen(e: SubmitEvent) {
    e.preventDefault();
    try {
      await api('/kategorien', { body: { name: neuName, emoji: neuEmoji, typ: neuTyp, ober: neuOber } });
      toast(neuOber ? `„${neuName}“ unter ${neuOber} angelegt` : `Kategorie „${neuName}“ angelegt`);
      neuOffen = false;
      laden();
    } catch (err) {
      fehler(err);
    }
  }

  async function kategorieLoeschen() {
    const k = eigene.get(gewaehlt!.name);
    if (!confirm(`Kategorie „${gewaehlt!.name}“ löschen? Ihre Buchungen ${k?.ober ? `gehen zurück zu „${k.ober}“` : 'werden wieder automatisch eingeordnet'}.`)) return;
    await api(`/kategorien/${encodeURIComponent(gewaehlt!.name)}`, { method: 'DELETE' }).catch(fehler);
    detailOffen = false;
    laden();
  }

  onMount(laden);
</script>

{#snippet symbole(aktuell: string, waehlen: (s: string) => void)}
  <div class="grid grid-cols-8 gap-1.5">
    {#each SYMBOLE as s (s)}
      <button type="button" class="grid aspect-square place-items-center rounded-xl text-[22px] {aktuell === s ? 'bg-accent-soft ring-2 ring-accent' : 'bg-card-hi active:bg-accent-soft'}" aria-label="Symbol {s}" aria-pressed={aktuell === s} onclick={() => waehlen(s)}>{s}</button>
    {/each}
  </div>
{/snippet}

<div class="px-4">
  <Header titel="Kategorien" zurueckZu="#/einstellungen">
    {#snippet aktionen()}
      <IconKnopf label="Kategorie anlegen" onclick={() => neuOeffnen()}><Plus size={24} /></IconKnopf>
    {/snippet}
  </Header>

  {#if !daten}
    <Laden form="liste" />
  {:else}
    <p class="-mt-2 text-[14px] leading-relaxed text-muted">
      Antippen, um Symbol, Unterkategorien und Regeln zu ändern. Regeln ordnen Buchungen anhand eines Stichworts in
      Empfänger oder Verwendungszweck ein – deine haben Vorrang vor den eingebauten.
    </p>
    {#each [['ausgabe', 'Ausgaben'], ['einnahme', 'Einnahmen']] as [typ, titel] (typ)}
      <h2 class="abschnitt">{titel}</h2>
      <div class="karte overflow-hidden">
        <!-- eigene Kategorien gelten in beide Richtungen, stehen hier aber nur einmal: dort, wo sie angelegt wurden -->
        {#each daten[typ].filter((n: string) => !daten.eigene.some((e: any) => e.name === n && e.typ !== typ && !e.ober)) as n (n)}
          {@const anzahl = regelnVon(n).length}
          {#key stand}
            <button class="zeile {ober[n] ? '!py-2.5 !pl-10' : ''}" onclick={() => oeffnen(n, typ as Typ)}>
              {#if ober[n]}<CornerDownRight size={16} class="shrink-0 text-faint" />{/if}
              <KategorieAvatar kategorie={n} groesse={ober[n] ? 32 : 38} />
              <span class="min-w-0 flex-1 truncate {ober[n] ? 'text-[15px]' : 'text-[16px]'}">{n}</span>
              {#if anzahl}<span class="text-[13px] text-accent">{anzahl} {anzahl === 1 ? 'Regel' : 'Regeln'}</span>{/if}
              {#if eigene.has(n)}<span class="rounded-md bg-card-hi px-1.5 py-0.5 text-[11px] text-muted">eigene</span>{/if}
              <ChevronRight size={18} class="shrink-0 text-faint" />
            </button>
          {/key}
        {/each}
      </div>
    {/each}
    <button class="knopf-sekundaer mt-6 w-full" onclick={() => neuOeffnen()}><Plus size={18} /> Kategorie anlegen</button>
  {/if}
</div>

<Sheet bind:offen={detailOffen} titel={gewaehlt?.name ?? ''}>
  {#if gewaehlt}
    {@const k = eigene.get(gewaehlt.name)}
    {#key stand}
      <div class="flex items-center gap-3.5">
        <KategorieAvatar kategorie={gewaehlt.name} groesse={56} />
        {#if k}
          <form class="flex min-w-0 flex-1 gap-2" onsubmit={(e) => { e.preventDefault(); if (name.trim() && name.trim() !== gewaehlt!.name) aendern({ name: name.trim() }, 'Umbenannt'); }}>
            <input class="feld min-w-0 flex-1" bind:value={name} maxlength="40" aria-label="Name der Kategorie" />
            {#if name.trim() && name.trim() !== gewaehlt.name}<button class="knopf-primaer !px-4">OK</button>{/if}
          </form>
        {:else}
          <div class="min-w-0 flex-1"><div class="truncate text-[18px] font-semibold">{gewaehlt.name}</div><div class="text-[13px] text-muted">Eingebaute Kategorie</div></div>
        {/if}
      </div>
    {/key}

    <h3 class="mb-2 mt-5 text-[14px] font-semibold text-muted">Symbol</h3>
    {#key stand}{@render symbole(emoji(gewaehlt.name), (s) => aendern({ emoji: s }, 'Symbol geändert'))}{/key}
    <form class="mt-2 flex gap-2" onsubmit={(e) => { e.preventDefault(); if (symbolFrei.trim()) aendern({ emoji: symbolFrei.trim() }, 'Symbol geändert'); symbolFrei = ''; }}>
      <input class="feld flex-1" placeholder="Anderes Symbol eintippen oder einfügen" maxlength="8" bind:value={symbolFrei} />
      <button class="knopf-sekundaer !px-4" disabled={!symbolFrei.trim()}>Setzen</button>
    </form>

    {#if k && !unterVon(gewaehlt.name).length}
      <h3 class="mb-2 mt-5 text-[14px] font-semibold text-muted">Unterkategorie von</h3>
      <KategorieWahl id="k-ober" wert={k.ober || null} optionen={oberOptionen(gewaehlt.name)} platzhalter="Eigenständig" onwahl={(o) => aendern({ ober: o }, `Jetzt unter ${o}`)} />
      {#if k.ober}
        <button class="mt-2 text-[14px] font-medium text-accent" onclick={() => aendern({ ober: '' }, 'Wieder eigenständig')}>Eigenständig machen</button>
      {:else}
        <p class="mt-1.5 text-[13px] text-muted">In den Analysen und Budgets zählt eine Unterkategorie bei ihrer Oberkategorie mit und steht darunter einzeln.</p>
      {/if}
    {/if}

    {#if !ober[gewaehlt.name]}
      <h3 class="mb-2 mt-5 text-[14px] font-semibold text-muted">Unterkategorien</h3>
      <div class="flex flex-wrap gap-1.5">
        {#each unterVon(gewaehlt.name) as u (u)}
          <button class="pill bg-card-hi" onclick={() => oeffnen(u, gewaehlt!.typ)}>{emoji(u)} {u}</button>
        {/each}
        <button class="pill-accent" onclick={() => neuOeffnen(gewaehlt!.name, gewaehlt!.typ)}><Plus size={14} /> Unterkategorie</button>
      </div>
    {/if}

    <h3 class="mb-2 mt-5 text-[14px] font-semibold text-muted">Regel hinzufügen</h3>
    <form class="flex gap-2" onsubmit={regelAnlegen}>
      <input class="feld flex-1" placeholder="Stichwort, z. B. rewe" bind:value={stichwort} autocapitalize="off" />
      <button class="knopf-primaer !px-4" disabled={stichwort.trim().length < 2}>Hinzufügen</button>
    </form>
    <p class="mt-2 px-1 text-[12px] text-faint">Gilt auch für vorhandene Buchungen.</p>

    {#if regelnVon(gewaehlt.name).length}
      <h3 class="mb-2 mt-5 text-[14px] font-semibold text-muted">Deine Regeln</h3>
      <div class="karte overflow-hidden">
        {#each regelnVon(gewaehlt.name) as r (r.id)}
          <div class="zeile">
            <span class="flex-1 font-mono text-[14px]">{r.stichwort}</span>
            <button class="grid size-8 place-items-center rounded-full text-neg active:bg-neg-soft" onclick={() => regelLoeschen(r.id)} aria-label="Regel löschen"><Trash2 size={17} /></button>
          </div>
        {/each}
      </div>
    {/if}
    {#if daten.eingebaut[gewaehlt.name]?.length}
      <h3 class="mb-2 mt-5 text-[14px] font-semibold text-muted">Eingebaute Stichworte</h3>
      <p class="text-[13px] leading-relaxed text-faint">{daten.eingebaut[gewaehlt.name].join(', ')}</p>
    {/if}
    {#if k}
      <button class="knopf-gefahr mt-6 w-full" onclick={kategorieLoeschen}>Kategorie löschen</button>
    {/if}
  {/if}
</Sheet>

<Sheet bind:offen={neuOffen} titel={neuOber ? `Unterkategorie von ${neuOber}` : 'Neue Kategorie'}>
  <form class="space-y-4" onsubmit={kategorieAnlegen}>
    <div class="flex items-center gap-3">
      <span class="grid size-12 shrink-0 place-items-center rounded-[14px] bg-card-hi text-[24px]">{neuEmoji}</span>
      <input class="feld min-w-0 flex-1" placeholder={neuOber ? 'z. B. Bäcker' : 'z. B. Haustier'} bind:value={neuName} maxlength="40" aria-label="Name" />
    </div>
    <div>
      <div class="label">Symbol</div>
      {@render symbole(neuEmoji, (s) => (neuEmoji = s))}
    </div>
    <div>
      <label class="label" for="k-neu-ober">Unterkategorie von</label>
      <KategorieWahl id="k-neu-ober" wert={neuOber || null} optionen={oberOptionen()} platzhalter="Eigenständig" onwahl={(o) => (neuOber = o)} />
      {#if neuOber}<button type="button" class="mt-2 text-[14px] font-medium text-accent" onclick={() => (neuOber = '')}>Doch eigenständig</button>{/if}
    </div>
    <button class="knopf-primaer w-full" disabled={!neuName.trim()}>Anlegen</button>
  </form>
</Sheet>
