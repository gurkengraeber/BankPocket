<script lang="ts">
  import { Plus, Target } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import BudgetRing from '../components/BudgetRing.svelte';
  import Header from '../components/Header.svelte';
  import IconKnopf from '../components/IconKnopf.svelte';
  import Laden from '../components/Laden.svelte';
  import Sheet from '../components/Sheet.svelte';
  import { api } from '../lib/api';
  import { monatName } from '../lib/format';
  import { emoji } from '../lib/kategorien';
  import { route } from '../lib/router.svelte';
  import { fehler, toast } from '../lib/store.svelte';

  let daten = $state<any>(null);
  let neuOffen = $state(route.query.get('neu') === '1');
  let bearbeiten = $state<any>(null);
  let bearbeitenOffen = $state(false);
  let kategorie = $state('');
  let betrag = $state('');

  const zahl = $derived(Number(betrag.replace(/\./g, '').replace(',', '.')));
  const heute = new Date();
  const tageRest = new Date(heute.getFullYear(), heute.getMonth() + 1, 0).getDate() - heute.getDate();

  async function laden() {
    try {
      daten = await api('/budgets');
      if (!daten.kategorien.includes(kategorie)) kategorie = daten.kategorien[0] ?? '';
    } catch (e) {
      fehler(e);
    }
  }

  async function anlegen(e: SubmitEvent) {
    e.preventDefault();
    try {
      await api('/budgets', { body: { kategorie, limit: zahl.toFixed(2) } });
      toast(`Budget für ${kategorie} angelegt`);
      betrag = '';
      neuOffen = false;
      laden();
    } catch (err) {
      fehler(err);
    }
  }

  async function speichern(e: SubmitEvent) {
    e.preventDefault();
    try {
      await api(`/budgets/${bearbeiten.id}`, { method: 'PATCH', body: { limit: zahl.toFixed(2) } });
      bearbeitenOffen = false;
      laden();
    } catch (err) {
      fehler(err);
    }
  }

  async function loeschen() {
    if (!confirm(`Budget für ${bearbeiten.kategorie} löschen?`)) return;
    await api(`/budgets/${bearbeiten.id}`, { method: 'DELETE' }).catch(fehler);
    bearbeitenOffen = false;
    laden();
  }

  function oeffnen(b: any) {
    bearbeiten = b;
    betrag = String(b.limit).replace('.', ',');
    bearbeitenOffen = true;
  }

  onMount(laden);
</script>

<div class="px-4">
  <Header titel="Budgets" zurueckZu="#/">
    {#snippet aktionen()}
      <IconKnopf label="Budget anlegen" onclick={() => { betrag = ''; neuOffen = true; }}><Plus size={24} /></IconKnopf>
    {/snippet}
  </Header>

  {#if !daten}
    <Laden />
  {:else}
    <p class="-mt-2 mb-5 text-[15px] text-muted">{monatName(daten.monat)} · noch {tageRest} {tageRest === 1 ? 'Tag' : 'Tage'}</p>
    {#if daten.budgets.length}
      <div class="karte overflow-hidden">
        {#each daten.budgets as b (b.id)}
          <button class="zeile" onclick={() => oeffnen(b)}>
            <BudgetRing kategorie={b.kategorie} anteil={b.anteil} status={b.status} groesse={50} />
            <span class="min-w-0 flex-1">
              <span class="flex items-baseline justify-between gap-3">
                <span class="truncate text-[17px]">{b.kategorie}</span>
                <span class="whitespace-nowrap text-[14px] text-muted"><Amount wert={b.ausgegeben} kurz /> von <Amount wert={b.limit} kurz /></span>
              </span>
              <span class="mt-1 block text-[13px] {b.status === 'ueberschritten' ? 'text-neg' : b.status === 'knapp' ? 'text-warn' : 'text-muted'}">
                {#if Number(b.rest) >= 0}noch <Amount wert={b.rest} /> übrig{:else}<Amount wert={-Number(b.rest)} /> über dem Budget{/if}
                {#if b.prognose !== null && b.status !== 'ueberschritten' && Number(b.prognose) > Number(b.limit)}
                  · bei diesem Tempo <Amount wert={b.prognose} kurz />
                {/if}
              </span>
            </span>
          </button>
        {/each}
      </div>
    {:else}
      <div class="karte flex flex-col items-center p-8 text-center">
        <span class="grid size-14 place-items-center rounded-full bg-accent-soft text-accent"><Target size={28} /></span>
        <p class="mt-4 text-[17px] font-semibold">Behalte deine Ausgaben im Blick</p>
        <p class="mt-1 text-[14px] text-muted">Lege für Kategorien wie Lebensmittel oder Restaurants ein Monatsbudget fest – BankPocket warnt dich bei 80 %.</p>
        <button class="knopf-primaer mt-5" onclick={() => (neuOffen = true)}><Plus size={18} /> Budget anlegen</button>
      </div>
    {/if}
  {/if}
</div>

<Sheet bind:offen={neuOffen} titel="Budget anlegen">
  <form class="space-y-4" onsubmit={anlegen}>
    <div>
      <label class="label" for="b-kat">Kategorie</label>
      <select id="b-kat" class="feld appearance-none" bind:value={kategorie}>
        {#each daten?.kategorien ?? [] as k (k)}<option value={k}>{emoji(k)}  {k}</option>{/each}
      </select>
    </div>
    <div>
      <label class="label" for="b-limit">Monatsbudget</label>
      <div class="relative">
        <input id="b-limit" class="feld pr-10 text-2xl font-semibold" inputmode="decimal" placeholder="300" bind:value={betrag} />
        <span class="absolute right-4 top-1/2 -translate-y-1/2 text-xl text-muted">€</span>
      </div>
    </div>
    <button class="knopf-primaer w-full" disabled={!kategorie || !(zahl > 0)}>Anlegen</button>
  </form>
</Sheet>

<Sheet bind:offen={bearbeitenOffen} titel={bearbeiten ? `Budget ${bearbeiten.kategorie}` : ''}>
  <form class="space-y-4" onsubmit={speichern}>
    <div>
      <label class="label" for="b-neu">Monatsbudget</label>
      <div class="relative">
        <input id="b-neu" class="feld pr-10 text-2xl font-semibold" inputmode="decimal" bind:value={betrag} />
        <span class="absolute right-4 top-1/2 -translate-y-1/2 text-xl text-muted">€</span>
      </div>
    </div>
    <button class="knopf-primaer w-full" disabled={!(zahl > 0)}>Speichern</button>
    <button type="button" class="knopf-gefahr w-full" onclick={loeschen}>Budget löschen</button>
  </form>
</Sheet>
