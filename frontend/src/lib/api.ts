import { auth } from './store.svelte';

export class ApiFehler extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Optionen = { method?: string; body?: unknown; form?: FormData };

export async function api<T = any>(pfad: string, opt: Optionen = {}): Promise<T> {
  const init: RequestInit = { method: opt.method ?? (opt.body || opt.form ? 'POST' : 'GET'), credentials: 'same-origin' };
  if (opt.form) init.body = opt.form;
  else if (opt.body !== undefined) {
    init.body = JSON.stringify(opt.body);
    init.headers = { 'Content-Type': 'application/json' };
  }
  let res: Response;
  try {
    res = await fetch(`/api${pfad}`, init);
  } catch {
    throw new ApiFehler(0, 'Server nicht erreichbar – bist du im Heimnetz?');
  }
  if (res.status === 401 && !pfad.startsWith('/login')) {
    auth.angemeldet = false;
    throw new ApiFehler(401, 'Bitte melde dich an.');
  }
  if (!res.ok) {
    const daten = await res.json().catch(() => ({}));
    const detail = typeof daten.detail === 'string' ? daten.detail : 'Etwas ist schiefgelaufen.';
    throw new ApiFehler(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}
