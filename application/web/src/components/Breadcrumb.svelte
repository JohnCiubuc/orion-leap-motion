<script>
  // Where you are in a nested menu (Root › Anki › Rating); every step but the last goes up to it.
  let { crumbs, onpick } = $props();
</script>

{#if crumbs.length > 1}
  <nav aria-label="Menu level">
    {#each crumbs as c, i (i)}
      {#if i}<span class="sep" aria-hidden="true">›</span>{/if}
      {#if i === crumbs.length - 1}
        <span class="here" aria-current="page">{c.label || "(no label)"}</span>
      {:else}
        <button class="ghost" onclick={() => onpick(c.path)}>{c.label}</button>
      {/if}
    {/each}
  </nav>
{/if}

<style>
  nav { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; font-size: 13px; }
  .sep { color: var(--dust); }
  .here { color: var(--star); font-weight: 600; }
  button { padding: 2px 8px; }
</style>
