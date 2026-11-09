function lesen(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function schreiben(key: string, wert: string) {
  try { localStorage.setItem(key, wert); } catch { /* privater Modus */ }
}

export const ui = $state({
  versteckt: lesen('bp_versteckt') === '1',
  budgetsAus: lesen('bp_budgets_aus') === '1',
  toast: null as null | { text: string; art: 'ok' | 'fehler' },
});

export const auth = $state({ geprueft: false, aktiv: true, angemeldet: false, passwort_gesetzt: true });

export function budgetsUmschalten() {
  ui.budgetsAus = !ui.budgetsAus;
  schreiben('bp_budgets_aus', ui.budgetsAus ? '1' : '0');
}

export function versteckenUmschalten() {
  ui.versteckt = !ui.versteckt;
  schreiben('bp_versteckt', ui.versteckt ? '1' : '0');
}

let toastTimer: ReturnType<typeof setTimeout> | undefined;
export function toast(text: string, art: 'ok' | 'fehler' = 'ok') {
  ui.toast = { text, art };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (ui.toast = null), art === 'fehler' ? 5000 : 2800);
}

export function fehler(e: unknown) {
  toast(e instanceof Error ? e.message : String(e), 'fehler');
}

export const merker = { lesen, schreiben };
