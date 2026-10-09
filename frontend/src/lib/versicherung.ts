// Wo ein Versicherungsvertrag liegt – wichtig, wenn man etwas ändern, kündigen oder einen Schaden melden will
export const VERWALTUNG: Record<string, string> = {
  direkt: 'Direkt beim Versicherer',
  makler: 'Makler',
  app: 'App',
  portal: 'Vergleichsportal',
  arbeitgeber: 'Arbeitgeber',
  bank: 'Bank',
  verband: 'Verein / Verband',
};
export const VERWALTUNG_KURZ: Record<string, string> = {
  direkt: 'Direkt', makler: 'Makler', app: 'App', portal: 'Portal', arbeitgeber: 'Arbeitgeber', bank: 'Bank', verband: 'Verband',
};
// gängige Namen zum Antippen
export const VERWALTUNG_NAMEN: Record<string, string[]> = {
  app: ['Clark', 'Getsafe', 'Feather', 'Check24', 'Knip', 'wefox'],
  portal: ['Check24', 'Verivox', 'Tarifcheck', 'Finanztip-Empfehlung'],
  bank: ['Sparkasse', 'Volksbank', 'ING', 'Consorsbank', 'DKB'],
  verband: ['ADAC', 'ver.di', 'Mieterverein', 'DAV'],
};
export const VERSICHERT: Record<string, string> = { ich: 'Nur ich', partner: 'Ich und Partner:in', familie: 'Familie', haushalt: 'Haushalt / WG' };

/** Aus „0341 1234“ oder „schaden.beispiel.de“ wird eine Adresse zum Antippen. */
export function kontaktLink(kontakt: string): string | null {
  const k = kontakt.trim();
  if (!k) return null;
  if (/^https?:\/\//i.test(k)) return k;
  if (/^[\d +()/-]{6,}$/.test(k)) return `tel:${k.replace(/[^\d+]/g, '')}`;
  if (/^\S+@\S+\.\S+$/.test(k)) return `mailto:${k}`;
  return /^[\w-]+(\.[\w-]+)+(\/\S*)?$/.test(k) ? `https://${k}` : null;
}
