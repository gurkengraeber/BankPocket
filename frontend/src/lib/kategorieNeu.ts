import { api } from './api';
import { kategorienMerken } from './kategorien';

type Kategorien = { ausgabe: string[]; einnahme: string[]; emoji?: Record<string, string>; ober?: Record<string, string> };

/** Kategorienliste laden – Symbole und Unterkategorien stehen danach überall bereit. */
export async function kategorienLaden(): Promise<Kategorien> {
  return kategorienMerken<Kategorien>(await api('/kategorien'));
}

/** Legt eine eigene Kategorie an und gibt die aktualisierte Kategorienliste zurück. */
export async function kategorieNeu(name: string, typ: 'ausgabe' | 'einnahme', ober = ''): Promise<Kategorien> {
  await api('/kategorien', { body: { name, emoji: '🏷️', typ, ober } });
  return kategorienLaden();
}
