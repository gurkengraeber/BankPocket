export type Route = { teile: string[]; query: URLSearchParams; pfad: string };

function parse(): Route {
  const roh = location.hash.replace(/^#\/?/, '');
  const [pfad, q = ''] = roh.split('?');
  return { pfad, teile: pfad.split('/').filter(Boolean).map(decodeURIComponent), query: new URLSearchParams(q) };
}

export const route = $state(parse());

window.addEventListener('hashchange', () => {
  Object.assign(route, parse());
  window.scrollTo(0, 0);
});

export function gehe(ziel: string) {
  location.hash = ziel.startsWith('#') ? ziel : `#${ziel}`;
}

export function zurueck(fallback = '#/') {
  if (history.length > 1 && document.referrer !== location.href) history.back();
  else gehe(fallback);
}
