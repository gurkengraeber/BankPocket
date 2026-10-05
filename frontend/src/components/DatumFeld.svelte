<script lang="ts">
  import { CalendarDays } from '@lucide/svelte';

  // Datum in deutscher Schreibweise (TT.MM.JJJJ) – unabhängig von der Sprache des Browsers.
  // Nach außen bleibt der Wert ein ISO-Datum (JJJJ-MM-TT), wie die Schnittstelle es erwartet; leer = kein Datum.
  let { id, wert = $bindable(''), max = '' }: { id: string; wert: string; max?: string } = $props();

  const alsText = (iso: string) => (/^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.split('-').reverse().join('.') : '');
  let text = $state(alsText(wert));
  let ungueltig = $state(false);
  let gemeldet = wert; // der zuletzt selbst gesetzte Wert – alles andere ist eine Änderung von außen

  // Änderungen von außen (Formular wird neu befüllt) übernehmen – nicht die eigene, halb getippte Eingabe überschreiben
  $effect(() => {
    if (wert !== gemeldet) {
      gemeldet = wert;
      text = alsText(wert);
      ungueltig = false;
    }
  });

  function lesen(eingabe: string): string | null {
    const t = eingabe.trim();
    // 31.12.2026, 31.12.26, 31.12., auch mit / - , oder Leerzeichen; ohne Trenner als 311226 oder 31122026
    const m = t.match(/^(\d{1,2})[.,/\- ]\s*(\d{1,2})(?:[.,/\- ]\s*(\d{2}|\d{4})?)?$/) ?? t.match(/^(\d{2})(\d{2})(\d{2}|\d{4})$/);
    if (!m) return null;
    const tag = Number(m[1]);
    const monat = Number(m[2]);
    const jahr = m[3] ? (m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3])) : new Date().getFullYear();
    const d = new Date(jahr, monat - 1, tag);
    if (d.getFullYear() !== jahr || d.getMonth() !== monat - 1 || d.getDate() !== tag) return null;
    const iso = `${jahr}-${String(monat).padStart(2, '0')}-${String(tag).padStart(2, '0')}`;
    return max && iso > max ? null : iso;
  }

  function setzen(iso: string) {
    gemeldet = iso;
    wert = iso;
  }

  // Beim Tippen wird nichts rot: Erst ein vollständiges Datum zählt, erst beim Verlassen wird geprüft
  function eingabe() {
    ungueltig = false;
    if (!text.trim()) setzen('');
    else {
      const iso = lesen(text);
      if (iso) setzen(iso);
    }
  }

  function verlassen() {
    if (!text.trim()) return;
    const iso = lesen(text);
    ungueltig = !iso;
    if (iso) text = alsText(iso);
  }
</script>

<div class="relative">
  <input
    {id}
    class="feld pr-14 {ungueltig ? '!border-neg' : ''}"
    inputmode="decimal"
    placeholder="TT.MM.JJJJ"
    autocomplete="off"
    bind:value={text}
    oninput={eingabe}
    onblur={verlassen}
    aria-invalid={ungueltig}
  />
  <!-- Kalender des Geräts: antippen statt tippen. Das eigentliche Datumsfeld liegt unsichtbar über dem Symbol. -->
  <span class="absolute right-1.5 top-1/2 grid size-11 -translate-y-1/2 place-items-center rounded-xl text-accent">
    <CalendarDays size={20} />
    <input
      type="date"
      class="absolute inset-0 size-full cursor-pointer opacity-0"
      aria-label="Datum im Kalender wählen"
      max={max || undefined}
      value={wert}
      onclick={(e) => { try { e.currentTarget.showPicker(); } catch { /* ältere Browser öffnen ihn selbst */ } }}
      onchange={(e) => { if (/^\d{4}-\d{2}-\d{2}$/.test(e.currentTarget.value)) { setzen(e.currentTarget.value); text = alsText(e.currentTarget.value); ungueltig = false; } }}
    />
  </span>
</div>
{#if ungueltig}<p class="mt-1 text-[12px] text-neg">Bitte als Tag.Monat.Jahr eingeben, z. B. 31.12.2026{max ? ' (nicht in der Zukunft)' : ''}.</p>{/if}
