// „Zum Startbildschirm hinzufügen“: Chrome auf Android bietet (nur über HTTPS) einen eigenen Dialog an,
// überall sonst geht es über das Browser-Menü – dann zeigt die App eine kurze Anleitung.
export const installation = $state<{ ereignis: any; installiert: boolean }>({
  ereignis: null,
  installiert: window.matchMedia('(display-mode: standalone)').matches || (navigator as any).standalone === true,
});

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  installation.ereignis = e;
});
window.addEventListener('appinstalled', () => {
  installation.installiert = true;
  installation.ereignis = null;
});
