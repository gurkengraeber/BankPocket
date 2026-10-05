const euroFmt = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' });
const euroKurz = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });

export function euro(wert: number | string | null | undefined, opt: { vorzeichen?: boolean; kurz?: boolean } = {}) {
  if (wert === null || wert === undefined || wert === '') return '–';
  const n = Number(wert);
  const text = (opt.kurz ? euroKurz : euroFmt).format(Math.abs(n));
  if (n < 0) return `−${text}`;
  return opt.vorzeichen && n > 0 ? `+${text}` : text;
}

function alsDatum(d: string | Date): Date {
  if (d instanceof Date) return d;
  return d.length === 10 ? new Date(`${d}T12:00:00`) : new Date(d);
}

function tagesDiff(d: Date): number {
  const a = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const h = new Date();
  const b = new Date(h.getFullYear(), h.getMonth(), h.getDate());
  return Math.round((a.getTime() - b.getTime()) / 86400000);
}

export function datumKurz(d: string | Date) {
  return alsDatum(d).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }) ;
}

export function datum(d: string | Date) {
  return alsDatum(d).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function tagUeberschrift(d: string) {
  const x = alsDatum(d);
  const diff = tagesDiff(x);
  if (diff === 0) return 'Heute';
  if (diff === -1) return 'Gestern';
  const jahr = x.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined;
  return x.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: jahr });
}

export function zeitpunkt(iso: string | null | undefined) {
  if (!iso) return 'noch nie';
  const x = alsDatum(iso);
  const uhr = x.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  const diff = tagesDiff(x);
  if (diff === 0) return `Heute, ${uhr} Uhr`;
  if (diff === -1) return `Gestern, ${uhr} Uhr`;
  return `${datumKurz(x)}, ${uhr} Uhr`;
}

export function inTagen(d: string) {
  const diff = tagesDiff(alsDatum(d));
  if (diff === 0) return 'heute';
  if (diff === 1) return 'morgen';
  if (diff === -1) return 'gestern';
  return diff > 0 ? `in ${diff} Tagen` : `vor ${-diff} Tagen`;
}

export function monatName(ym: string, kurz = false) {
  const [j, m] = ym.split('-').map(Number);
  return new Date(j, m - 1, 1).toLocaleDateString('de-DE', kurz ? { month: 'short' } : { month: 'long', year: 'numeric' });
}

export function vorZeit(iso: string) {
  const min = Math.round((Date.now() - alsDatum(iso).getTime()) / 60000);
  if (min < 1) return 'gerade eben';
  if (min < 60) return `vor ${min} Min.`;
  if (min < 24 * 60) return `vor ${Math.round(min / 60)} Std.`;
  return datumKurz(iso);
}

export const TURNUS: Record<string, string> = {
  woechentlich: 'Wöchentlich',
  zweiwoechentlich: 'Alle 2 Wochen',
  vierwoechentlich: 'Alle 4 Wochen',
  halbmonatlich: '2× im Monat',
  monatlich: 'Monatlich',
  quartalsweise: 'Vierteljährlich',
  halbjaehrlich: 'Halbjährlich',
  jaehrlich: 'Jährlich',
};
