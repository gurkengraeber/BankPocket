import { api } from './api';

export type PushZustand = 'nicht_moeglich' | 'blockiert' | 'aus' | 'an';

export function pushMoeglich() {
  return window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

export async function pushZustand(): Promise<PushZustand> {
  if (!pushMoeglich()) return 'nicht_moeglich';
  if (Notification.permission === 'denied') return 'blockiert';
  const reg = await navigator.serviceWorker.getRegistration();
  return (await reg?.pushManager.getSubscription()) ? 'an' : 'aus';
}

function schluesselBytes(b64: string) {
  const pad = '='.repeat((4 - (b64.length % 4)) % 4);
  const roh = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(roh, (c) => c.charCodeAt(0));
}

export async function pushAktivieren() {
  if ((await Notification.requestPermission()) !== 'granted') throw new Error('Benachrichtigungen wurden nicht erlaubt.');
  const reg = await navigator.serviceWorker.ready;
  const { schluessel } = await api('/push');
  const abo = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: schluesselBytes(schluessel) });
  await api('/push/abo', { body: abo.toJSON() });
}

export async function pushDeaktivieren() {
  const reg = await navigator.serviceWorker.getRegistration();
  const abo = await reg?.pushManager.getSubscription();
  if (!abo) return;
  await api('/push/abo', { method: 'DELETE', body: { endpoint: abo.endpoint } });
  await abo.unsubscribe();
}
