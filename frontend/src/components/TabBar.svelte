<script lang="ts">
  import { ChartColumnBig, LayoutDashboard, PiggyBank, Repeat, ShieldCheck } from '@lucide/svelte';

  // nurBreit: auf dem Handy ausgeblendet (Seiten ohne Tabs), am PC bleibt die Seitenleiste stehen
  let { aktiv, nurBreit = false }: { aktiv: string; nurBreit?: boolean } = $props();
  const tabs = [
    { id: 'uebersicht', href: '#/', label: 'Übersicht', icon: LayoutDashboard },
    { id: 'vertraege', href: '#/vertraege', label: 'Verträge', icon: Repeat },
    { id: 'sparen', href: '#/sparen', label: 'Sparen', icon: PiggyBank },
    { id: 'analysen', href: '#/analysen', label: 'Analysen', icon: ChartColumnBig },
    { id: 'versicherungen', href: '#/versicherungen', label: 'Versicherungen', kurz: 'Versichert', icon: ShieldCheck },
  ];
</script>

<nav
  class="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-bg/90 backdrop-blur-xl lg:inset-y-0 lg:right-auto lg:w-60 lg:border-r lg:border-t-0 {nurBreit
    ? 'max-lg:hidden'
    : ''}"
  style="padding-bottom: env(safe-area-inset-bottom)"
>
  <a href="#/" class="hidden items-center gap-3 px-6 pb-6 pt-7 text-[19px] font-bold tracking-tight lg:flex">
    <img src="/icon.svg" alt="" class="size-9 rounded-xl" />BankPocket
  </a>
  <div class="mx-auto flex max-w-[480px] justify-around px-1 py-2 lg:flex-col lg:justify-start lg:gap-1 lg:px-3 lg:py-0">
    {#each tabs as t (t.id)}
      {@const an = aktiv === t.id}
      <a
        href={t.href}
        class="flex min-w-0 flex-1 flex-col items-center gap-1 py-0.5 text-[11px] font-semibold transition-colors lg:w-full lg:flex-row lg:gap-3 lg:rounded-2xl lg:px-3 lg:py-2 lg:text-[15px] lg:hover:bg-card {an
          ? 'text-accent'
          : 'text-muted'}"
        aria-current={an ? 'page' : undefined}
      >
        <span class="grid h-8 w-12 place-items-center rounded-full transition-colors lg:size-9 {an ? 'bg-accent-soft' : ''}">
          <t.icon size={22} strokeWidth={an ? 2.4 : 2} />
        </span>
        <span class="max-w-full truncate lg:hidden">{t.kurz ?? t.label}</span><span class="hidden lg:inline">{t.label}</span>
      </a>
    {/each}
  </div>
</nav>
