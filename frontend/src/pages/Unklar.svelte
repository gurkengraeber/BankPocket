<script lang="ts">
  import { ArrowRightLeft, Check } from '@lucide/svelte';
  import { onMount } from 'svelte';
  import Amount from '../components/Amount.svelte';
  import Header from '../components/Header.svelte';
  import KategorieWahl from '../components/KategorieWahl.svelte';
  import Laden from '../components/Laden.svelte';
  import { api } from '../lib/api';
  import { datum } from '../lib/format';
  import { kategorieNeu, kategorienLaden } from '../lib/kategorieNeu';
  import { emoji } from '../lib/kategorien';
  import { fehler, toast } from '../lib/store.svelte';

  let daten = $state<any>(null);
  let kategorien = $state<{ ausgabe: string[]; einnahme: string[] } | null>(null);
  let merken = $state<Record<string, boolean>>({});

  const schluessel = (g: any) => `${g.typ}|${g.ids[0]}`;

  async function laden() {
    try {
      [daten, kategorien] = await Promise.all([api('/unklar'), kategorienLaden()]);
    } catch (e) {
      fehler(e);
    }
  }

  async function zuordnen(g: any, body: Record<string, unknown>, meldung: string) {
    try {
      const r = await api('/unklar', { body: { ids: g.ids, haendler: g.haendler, merken: merken[schluessel(g)] ?? g.haendler.length >= 3, ...body } });
      daten.gruppen = daten.gruppen.filter((x: any) => x !== g);
      toast(meldung);
      // Eine gemerkte Regel kann weitere Gruppen miterledigt haben
      if (r.offen !== daten.gruppen.reduce((n: number, x: any) => n + x.anzahl, 0)) laden();
      else daten.anzahl = r.offen;
    } catch (e) {
      fehler(e);
    }
  }

  // Unsichere Umbuchungen: gehören Abgang und Zugang zusammen?
  async function paarAntwort(p: any, ja: boolean) {
    try {
      await api(ja ? '/umbuchungen' : '/umbuchungen/ablehnen', { body: { a: p.abgang.id, b: p.zugang.id } });
      toast(ja ? 'Als Umbuchung verbunden' : 'Wird nicht mehr vorgeschlagen');
      laden();
    } catch (e) {
      fehler(e);
    }
  }

  async function neueKategorie(g: any, name: string) {
    try {
      kategorien = await kategorieNeu(name, g.typ);
      await zuordnen(g, { kategorie: name }, `${g.haendler || 'Buchung'} → ${name}`);
    } catch (e) {
      fehler(e);
    }
  }

  onMount(laden);
</script>

<div class="px-4">
  <Header titel="Unklare Buchungen" gross={false} zurueckZu="#/analysen" />

  {#if !daten || !kategorien}
    <Laden form="liste" />
  {:else if !daten.gruppen.length && !daten.umbuchungen.length}
    <div class="karte mt-6 p-8 text-center">
      <div class="mx-auto grid size-14 place-items-center rounded-full bg-accent-soft text-accent"><Check size={28} /></div>
      <div class="mt-4 text-[18px] font-semibold">Alles eingeordnet</div>
      <p class="mt-1 text-[14px] text-muted">Es gibt keine Buchungen ohne Kategorie.</p>
    </div>
  {:else}
    {#if daten.umbuchungen.length}
      <h2 class="abschnitt !pt-3">Gehört das zusammen? <span class="font-semibold text-muted">({daten.umbuchungen.length})</span></h2>
      <p class="px-1 pb-3 text-[14px] text-muted">
        Gleicher Betrag, einmal raus und einmal rein auf zwei deiner Konten. Ist das eine Umbuchung, zählt sie weder als
        Ausgabe noch als Einnahme.
      </p>
      <div class="mb-6 space-y-3 lg:grid lg:grid-cols-2 lg:items-start lg:gap-4 lg:space-y-0">
        {#each daten.umbuchungen as p (p.abgang.id)}
          <div class="karte p-4">
            {#each [p.abgang, p.zugang] as t (t.id)}
              <div class="flex items-center gap-3 py-1.5">
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[16px]">{t.konto_name}</span>
                  <span class="block truncate text-[13px] text-muted">{datum(t.datum)}{t.gegenpartei ? ` · ${t.gegenpartei}` : ''}</span>
                </span>
                <Amount wert={t.betrag} vorzeichen farbig klasse="text-[16px] font-medium" />
              </div>
            {/each}
            <div class="mt-3 grid grid-cols-2 gap-2">
              <button class="knopf-sekundaer !py-2.5" onclick={() => paarAntwort(p, false)}>Nein</button>
              <button class="knopf-primaer !py-2.5" onclick={() => paarAntwort(p, true)}><ArrowRightLeft size={16} /> Ja, Umbuchung</button>
            </div>
          </div>
        {/each}
      </div>
    {/if}

    {#if daten.gruppen.length}
    <p class="mb-4 mt-3 text-[15px] text-muted">
      {daten.anzahl - daten.umbuchungen.length} {daten.anzahl - daten.umbuchungen.length === 1 ? 'Buchung konnte' : 'Buchungen konnten'} weder die Regeln noch die KI einordnen.
      Wähle je Händler eine Kategorie – BankPocket merkt sie sich für künftige Buchungen.
    </p>
    <div class="space-y-3 lg:grid lg:grid-cols-2 lg:items-start lg:gap-4 lg:space-y-0">
      {#each daten.gruppen as g (schluessel(g))}
        <div class="karte p-4">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="truncate text-[17px] font-semibold">{g.haendler || 'Ohne Namen'}</div>
              <div class="mt-0.5 text-[13px] text-muted">
                {g.anzahl} {g.anzahl === 1 ? 'Buchung' : 'Buchungen'} · zuletzt {datum(g.letzte)} · {g.konto}
              </div>
              {#if g.zweck || g.art}<div class="mt-0.5 truncate text-[13px] text-faint">{g.zweck || g.art}</div>{/if}
            </div>
            <Amount wert={g.summe} vorzeichen farbig klasse="text-[17px] font-semibold" />
          </div>
          <div class="mt-3 flex flex-wrap gap-1.5">
            {#each daten.haeufig[g.typ] as k (k)}
              <button class="pill border border-line bg-card active:bg-card-hi" onclick={() => zuordnen(g, { kategorie: k }, `${g.haendler || 'Buchung'} → ${k}`)}>
                {emoji(k)} {k}
              </button>
            {/each}
          </div>
          <div class="mt-2">
            <KategorieWahl
              id="k-{schluessel(g)}"
              wert={null}
              optionen={kategorien[g.typ as 'ausgabe' | 'einnahme']}
              platzhalter="Andere Kategorie suchen oder anlegen"
              onwahl={(k) => zuordnen(g, { kategorie: k }, `${g.haendler || 'Buchung'} → ${k}`)}
              onneu={(name) => neueKategorie(g, name)}
            />
          </div>
          <div class="mt-3 flex flex-wrap items-center justify-between gap-2 text-[13px]">
            {#if g.haendler.length >= 3}
              <label class="flex items-center gap-2 text-muted">
                <input type="checkbox" class="size-4 accent-[var(--color-accent)]" checked={merken[schluessel(g)] ?? true} onchange={(e) => (merken[schluessel(g)] = e.currentTarget.checked)} />
                Für diesen Händler merken
              </label>
            {:else}<span></span>{/if}
            <button class="flex items-center gap-1.5 font-medium text-accent" onclick={() => zuordnen(g, { umbuchung: true }, 'Als Umbuchung markiert')}>
              <ArrowRightLeft size={14} /> Ist eine Umbuchung
            </button>
          </div>
        </div>
      {/each}
    </div>
    {/if}
  {/if}
</div>
