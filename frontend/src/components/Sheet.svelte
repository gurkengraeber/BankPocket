<script lang="ts">
  import type { Snippet } from 'svelte';
  import { fade, fly } from 'svelte/transition';

  let { offen = $bindable(false), titel = '', children }: { offen: boolean; titel?: string; children: Snippet } = $props();

  $effect(() => {
    if (!offen) return;
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && (offen = false);
    window.addEventListener('keydown', esc);
    document.documentElement.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', esc);
      document.documentElement.style.overflow = '';
    };
  });

  // Nach unten wegwischen: am Griff jederzeit, im Inhalt nur, wenn er ganz oben steht (sonst wird gescrollt)
  let versatz = $state(0);
  let zieht = $state(false);
  let weggewischt = $state(false);
  $effect(() => {
    if (offen) {
      versatz = 0;
      weggewischt = false;
    }
  });

  // Beim Wegwischen ist das Fenster schon unten angekommen – dann ohne weitere Animation verschwinden
  const raus = (node: Element) =>
    weggewischt ? { duration: 60, css: () => 'transform: translateY(110vh)' } : fly(node, { y: 420, duration: 280, opacity: 1 });

  function wischen(el: HTMLElement) {
    let startY = 0;
    let startZeit = 0;
    let aktiv = false;
    const start = (e: TouchEvent) => {
      const ziel = e.target as HTMLElement;
      const amGriff = !!ziel.closest('[data-griff]');
      // in Eingabefeldern und beim Scrollen des Inhalts nicht dazwischenfunken
      aktiv = e.touches.length === 1 && (amGriff || (el.scrollTop <= 0 && !ziel.closest('input, textarea, select, [data-kein-wischen]')));
      startY = e.touches[0].clientY;
      startZeit = Date.now();
    };
    const bewegen = (e: TouchEvent) => {
      if (!aktiv) return;
      const dy = e.touches[0].clientY - startY;
      if (dy <= 0) {
        if (!zieht) aktiv = false; // nach oben: normales Scrollen
        versatz = 0;
        return;
      }
      if (!zieht && dy < 8) return;
      zieht = true;
      versatz = dy;
      if (e.cancelable) e.preventDefault(); // die Seite dahinter bleibt stehen
    };
    const ende = () => {
      if (!zieht) return;
      zieht = false;
      const schnell = versatz > 40 && versatz / Math.max(Date.now() - startZeit, 1) > 0.6;
      if (versatz > Math.min(140, el.offsetHeight / 3) || schnell) {
        weggewischt = true;
        versatz = el.offsetHeight + 40;
        setTimeout(() => (offen = false), 180);
      } else versatz = 0;
    };
    el.addEventListener('touchstart', start, { passive: true });
    el.addEventListener('touchmove', bewegen, { passive: false });
    el.addEventListener('touchend', ende);
    el.addEventListener('touchcancel', ende);
    return {
      destroy() {
        el.removeEventListener('touchstart', start);
        el.removeEventListener('touchmove', bewegen);
        el.removeEventListener('touchend', ende);
        el.removeEventListener('touchcancel', ende);
      },
    };
  }
</script>

{#if offen}
  <div
    class="fixed inset-0 z-50 bg-black/65"
    style={versatz ? `opacity: ${Math.max(0.25, 1 - versatz / 500)}` : ''}
    transition:fade={{ duration: 160 }}
    onclick={() => (offen = false)}
    role="presentation"
  ></div>
  <div
    class="fixed inset-x-0 bottom-0 z-50 mx-auto max-h-[92dvh] max-w-[480px] overflow-y-auto overscroll-contain rounded-t-[28px] bg-sheet px-4 lg:bottom-auto lg:top-1/2 lg:-translate-y-1/2 lg:rounded-[28px]"
    style="padding-bottom: calc(env(safe-area-inset-bottom) + 20px); {versatz ? `transform: translateY(${versatz}px);` : ''} {zieht ? '' : 'transition: transform 180ms ease-out;'}"
    in:fly={{ y: 420, duration: 280, opacity: 1 }}
    out:raus
    use:wischen
    role="dialog"
    aria-modal="true"
    aria-label={titel}
  >
    <!-- der Griff: großzügige Fläche zum Anfassen; antippen schließt ebenfalls -->
    <button type="button" data-griff class="mx-auto flex h-8 w-full items-center justify-center lg:cursor-default" onclick={() => (offen = false)} aria-label="Schließen">
      <span class="h-1.5 w-10 rounded-full bg-line"></span>
    </button>
    {#if titel}<h2 class="mb-5 mt-1 text-[22px] font-bold tracking-tight">{titel}</h2>{/if}
    {@render children()}
  </div>
{/if}
