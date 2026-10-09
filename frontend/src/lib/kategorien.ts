const EMOJI: Record<string, string> = {
  Miete: '🏠', Strom: '⚡', 'Internet & Telefon': '📶', Streaming: '🎬', 'Software/KI': '🤖',
  Versicherung: '🛡️', Mitgliedschaft: '🎫', Coworking: '💼', Fitness: '🏋️', Mobilität: '🚆', Sparen: '📈',
  Lebensmittel: '🛒', Drogerie: '🧴', Restaurants: '🍽️', Shopping: '🛍️', Tanken: '⛽', Gesundheit: '💊',
  Reisen: '✈️', Bargeld: '🏧', Sonstiges: '📄', 'Lohn / Gehalt': '💰', Zinsen: '🏦',
  'Sonstige Einnahmen': '💸', Umbuchung: '🔁', Spenden: '💝', Bildung: '📚', 'Gebühren & Steuern': '🧾',
  Haustier: '🐾', Freizeit: '🎟️', Dividenden: '📊', 'Staatliche Leistungen': '🏛️', Erstattung: '↩️',
  Verkäufe: '🏷️',
};

const FARBEN = ['#7fa8ff', '#4fb0c6', '#ff8f6b', '#f5c542', '#5ec8ff', '#ff6fae', '#a3e05a', '#c08bff', '#ffb26b', '#4fd1a1'];

// Emojis eigener Kategorien (und eigene Symbole für eingebaute) – beim Start und nach Änderungen aus
// /api/kategorien gefüllt
export const eigeneEmoji: Record<string, string> = {};
// Unterkategorie → Oberkategorie
export const oberVon: Record<string, string> = {};

/** Symbole und Unterkategorien aus einer Antwort von /api/kategorien übernehmen. */
export function kategorienMerken<T extends { emoji?: Record<string, string>; ober?: Record<string, string> }>(daten: T): T {
  for (const k of Object.keys(eigeneEmoji)) delete eigeneEmoji[k];
  for (const k of Object.keys(oberVon)) delete oberVon[k];
  Object.assign(eigeneEmoji, daten.emoji ?? {});
  Object.assign(oberVon, daten.ober ?? {});
  return daten;
}

// Auswahl an Symbolen zum Antippen – beliebige andere lassen sich eintippen
export const SYMBOLE = ['🏠', '⚡', '💧', '🔥', '📶', '📱', '🎬', '🎵', '🎮', '🤖', '💻', '🛡️', '🎫', '💼', '🏋️', '⚽', '🧘', '🚆', '🚌', '🚗', '🚲', '✈️', '⛽', '🅿️',
  '📈', '🪙', '🏦', '💰', '💸', '💳', '🛒', '🥐', '🥦', '🍽️', '☕', '🍺', '🍕', '🧴', '💊', '🩺', '🦷', '👓', '🛍️', '👕', '👟', '🎁', '📚', '🎓', '✏️',
  '🧾', '🏛️', '⚖️', '💝', '🤝', '👶', '🧸', '🐾', '🌱', '🔧', '🛠️', '🧹', '🛋️', '📦', '✂️', '🎟️', '🎭', '🏕️', '🏖️', '🎄', '📰', '📄', '🏷️', '↩️', '🔁', '❓'];

export function emoji(kategorie: string | null | undefined) {
  return eigeneEmoji[kategorie ?? ''] ?? EMOJI[kategorie ?? ''] ?? '📄';
}

export function farbe(text: string) {
  let h = 0;
  for (const c of text) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return FARBEN[h % FARBEN.length];
}

// Kachelfarben für Banken/Quellen – nur Farben und Kürzel, keine Logos
const BANKEN: Record<string, { bg: string; fg: string; text: string }> = {
  ing: { bg: '#ff6200', fg: '#ffffff', text: 'ING' },
  consorsbank: { bg: '#1f9bc4', fg: '#ffffff', text: 'C' },
  paypal: { bg: '#0b3a8f', fg: '#ffffff', text: 'PP' },
  norwegian: { bg: '#d81939', fg: '#ffffff', text: 'N' },
  n26: { bg: '#36a18b', fg: '#ffffff', text: 'N26' },
  revolut: { bg: '#191c1f', fg: '#ffffff', text: 'R' },
  trade_republic: { bg: 'var(--color-card-hi)', fg: 'var(--color-text)', text: 'TR' },
  binance: { bg: '#f0b90b', fg: '#1a1a1a', text: 'B' },
  splitwise: { bg: '#3fb68b', fg: '#ffffff', text: 'S' },
  sparkasse: { bg: '#ff0000', fg: '#ffffff', text: 'S' },
  volksbank: { bg: '#0066b3', fg: '#ffffff', text: 'VR' },
  dkb: { bg: '#148dea', fg: '#ffffff', text: 'DKB' },
  comdirect: { bg: '#fff500', fg: '#1a1a1a', text: 'c' },
  postbank: { bg: '#ffcc00', fg: '#0a2a7a', text: 'P' },
  deutsche_bank: { bg: '#0018a8', fg: '#ffffff', text: 'DB' },
  commerzbank: { bg: '#ffd200', fg: '#1a1a1a', text: 'CB' },
  andere: { bg: 'var(--color-card-hi)', fg: 'var(--color-text)', text: '🏦' },
};

export function bankKachel(quelle: string, name = '') {
  if (BANKEN[quelle]) return BANKEN[quelle];
  const n = name.toLowerCase();
  if (quelle === 'manuell') {
    const e = n.includes('bargeld') ? '💶' : n.includes('splitwise') ? '🤝' : n.includes('kaution') || n.includes('schuld') ? '🔑'
      : n.includes('monero') || n.includes('exodus') || n.includes('krypto') ? '🪙' : '✍️';
    return { bg: 'var(--color-card-hi)', fg: 'var(--color-text)', text: e };
  }
  return { bg: farbe(name || quelle), fg: '#04211c', text: (name || quelle).slice(0, 1).toUpperCase() };
}

// Farben für Tortendiagramme: nach Rang vergeben, damit sich Nachbarn unterscheiden
export const TORTENFARBEN = ['#2f6fde', '#f0a63a', '#2fb8a0', '#e8637a', '#8fc7f5', '#b88cf0', '#8fc93a', '#f28a4e', '#5cc8d8',
  '#d870c8', '#c2b04a', '#8a93a8'];

// Logos der Banken: Adresse, deren Seitensymbol der Server einmal holt (siehe bankpocket/logos.py)
const BANK_LOGO: Record<string, string> = {
  ing: 'ing.de', consorsbank: 'consorsbank.de', paypal: 'paypal.com', norwegian: 'banknorwegian.de',
  enablebanking: 'banknorwegian.de', n26: 'n26.com', revolut: 'revolut.com', trade_republic: 'traderepublic.com', binance: 'binance.com',
  splitwise: 'splitwise.com', sparkasse: 'sparkasse.de', volksbank: 'vr.de', dkb: 'dkb.de', comdirect: 'comdirect.de',
  postbank: 'postbank.de', deutsche_bank: 'deutsche-bank.de', commerzbank: 'commerzbank.de',
};
const BANK_LOGO_NAME: [string, string][] = [
  ['consors', 'consorsbank.de'], ['trade republic', 'traderepublic.com'], ['norwegian', 'banknorwegian.de'],
  ['paypal', 'paypal.com'], ['splitwise', 'splitwise.com'], ['binance', 'binance.com'], ['sparkasse', 'sparkasse.de'],
  ['volksbank', 'vr.de'], ['raiffeisen', 'vr.de'], ['comdirect', 'comdirect.de'], ['postbank', 'postbank.de'],
  ['deutsche bank', 'deutsche-bank.de'], ['commerzbank', 'commerzbank.de'], ['dkb', 'dkb.de'], ['n26', 'n26.com'],
  ['barclays', 'barclays.de'], ['c24', 'c24.de'], ['scalable', 'scalable.capital'], ['revolut', 'revolut.com'],
  ['wise', 'wise.com'], ['exodus', 'exodus.com'], ['monero', 'getmonero.org'], ['ing', 'ing.de'],
];

export function bankLogo(quelle: string, name = ''): string | null {
  if (BANK_LOGO[quelle]) return BANK_LOGO[quelle];
  const n = ` ${name.toLowerCase()} `;
  // Der Name entscheidet bei CSV- und manuellen Konten; „ing“ nur als eigenes Wort
  return BANK_LOGO_NAME.find(([wort]) => (wort === 'ing' ? /[^a-zäöü]ing[^a-zäöü]/.test(n) : n.includes(wort)))?.[1] ?? null;
}
