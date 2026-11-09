<script lang="ts">
  let { n }: { n: number } = $props();
</script>

<span
  class="absolute -right-1.5 -top-1.5 grid h-5 min-w-5 place-items-center rounded-full bg-accent px-1 text-[11px] font-bold text-accent-ink ring-2 ring-card"
>
  {n > 99 ? '99+' : n}
</span>
