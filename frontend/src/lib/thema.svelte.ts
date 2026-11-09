// Helles oder dunkles Design: „auto“ folgt dem Gerät, sonst gilt die Wahl aus den Einstellungen.
import { merker } from './store.svelte';

export type Thema = 'auto' | 'hell' | 'dunkel';

const hellesGeraet = window.matchMedia('(prefers-color-scheme: light)');

export const thema = $state<{ wahl: Thema }>({ wahl: (merker.lesen('bp_thema') as Thema) ?? 'auto' });

function anwenden() {
  const hell = thema.wahl === 'hell' || (thema.wahl === 'auto' && hellesGeraet.matches);
  document.documentElement.dataset.theme = hell ? 'light' : 'dark';
  document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', hell ? 'light' : 'dark');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', hell ? '#f5f3ee' : '#0e1016');
}

export function themaSetzen(wahl: Thema) {
  thema.wahl = wahl;
  merker.schreiben('bp_thema', wahl);
  anwenden();
}

export function themaStarten() {
  anwenden();
  hellesGeraet.addEventListener('change', anwenden);
}
