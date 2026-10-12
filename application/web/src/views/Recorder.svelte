<script>
  // Record tracking sessions and replay them through the gesture pipeline (great for tuning).
  import { Circle, Square, Play, FolderOpen } from "@lucide/svelte";
  import { orion, send } from "../lib/link.svelte.js";

  const s = $derived(orion.status);
  const replaying = $derived(s.source === "replay");
  const when = (f) => f.replace(".orec", "").replace("_", " at ").replace(/-(\d\d)-(\d\d)$/, ":$1:$2");
</script>

<header>
  <h1>Recorder</h1>
  <p class="muted">Record a session, then replay it to test gestures and tuning without moving your hands.</p>
</header>

<div class="cols">
  <section class="panel rec">
    <button class="big" class:on={s.recording} onclick={() => send("record", { on: !s.recording })}>
      {#if s.recording}<Square size={18} /> Stop recording{:else}<Circle size={18} /> Start recording{/if}
    </button>
    <p class="muted">{s.recording ? "Recording every tracking frame…" : "Saves to ~/.local/share/orion-renewal/recordings"}</p>
    {#if replaying}
      <div class="replay">
        <p>Replaying <b>{s.device}</b>. Live tracking is paused.</p>
        <button onclick={() => send("replay", { file: null })}>Back to live device</button>
      </div>
    {/if}
  </section>

  <section class="panel">
    <div class="sh"><h2>Recordings</h2>
      <button class="ghost" onclick={() => send("reveal", { what: "recordings" })}><FolderOpen size={15} /> Open folder</button></div>
    {#each orion.recordings as f (f)}
      <div class="row">
        <span>{when(f)}</span>
        <button onclick={() => send("replay", { file: f })} disabled={s.recording}><Play size={14} /> Replay</button>
      </div>
    {:else}
      <p class="muted">No recordings yet.</p>
    {/each}
  </section>
</div>

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 22px; flex-wrap: wrap; }
  .cols { display: grid; grid-template-columns: 340px minmax(0, 560px); gap: 16px; align-items: start; }
  section { padding: 18px; display: grid; gap: 12px; }
  .big { justify-content: center; padding: 14px; font-size: 15px; font-weight: 600; }
  .big.on { border-color: var(--bad); color: var(--bad); }
  .big.on :global(svg) { fill: currentColor; }
  .replay { padding: 12px; border-radius: var(--r-sm); background: #ffa46314; border: 1px solid #ffa46340; display: grid; gap: 8px; }
  .sh { display: flex; justify-content: space-between; align-items: center; }
  .row { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }
  @media (max-width: 1000px) { .cols { grid-template-columns: 1fr; } }
</style>
