<script>
  // Recent gestures, newest first, with the actions they triggered.
  import { orion } from "../lib/link.svelte.js";
  let { limit = 30 } = $props();
  // Hide the chatter of unbound continuous/joystick starts (pointer, pinch_joy …) — they begin constantly.
  const continuous = $derived(new Set(orion.gestures.filter((g) => ["continuous", "joystick"].includes(g.family)).map((g) => g.name)));
  const items = $derived(orion.feed.filter((e) => e.phase !== "end" && (e.actions.length || !continuous.has(e.name))).slice(0, limit));
</script>

<ol class="feed">
  {#each items as e, i (e.t + e.name + i)}
    <li class={e.hand === "left" || e.hand === "right" ? e.hand : ""}>
      <span class="dot"></span>
      <div>
        <code>{e.name}</code>
        {#if e.count}<span class="muted"> ×{e.count}</span>
        {:else if typeof e.value === "number"}<span class="muted"> {e.value.toFixed(2)}</span>{/if}
        <div class="acts">
          {#each e.actions as a}<span class="act">{orion.status.dry_run ? "would run " : ""}{a}</span>
          {:else}<span class="muted small">No binding in {e.profile}</span>{/each}
        </div>
      </div>
    </li>
  {:else}
    <li class="empty muted">Make a gesture over the device — it will show up here.</li>
  {/each}
</ol>

<style>
  .feed { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
  li { display: grid; grid-template-columns: 14px 1fr; gap: 8px; padding: 7px 4px; border-bottom: 1px solid #25306066; }
  li:first-child code { color: var(--hand, var(--star)); }
  .dot { width: 7px; height: 7px; border-radius: 50%; margin-top: 7px; background: var(--hand, var(--dust)); box-shadow: 0 0 6px var(--hand, transparent); }
  .acts { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
  .act { font-size: 11.5px; padding: 1px 7px; border-radius: 99px; background: var(--nebula-2); color: var(--dust); }
  .small { font-size: 11.5px; }
  .empty { display: block; border: 0; padding: 18px 4px; }
</style>
