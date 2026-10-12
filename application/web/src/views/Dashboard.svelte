<script>
  // Live view: 3D constellation hands, per-hand readouts, raw IR, gesture feed.
  import HandView from "../components/HandView.svelte";
  import IRView from "../components/IRView.svelte";
  import EventFeed from "../components/EventFeed.svelte";
  import { orion } from "../lib/link.svelte.js";

  const FINGERS = ["Thumb", "Index", "Middle", "Ring", "Pinky"];
  let palette = $state("night");
  const sentence = $derived.by(() => {
    const n = orion.hands.length, s = orion.status;
    if (!orion.connected) return "Waiting for the Orion engine.";
    if (!s.connected) return "No Leap Motion found. Plug it in and check the tracking service.";
    if (!s.streaming) return "The controller is connected but not sending frames. Restart it from the sidebar.";
    const who = n === 0 ? "No hands in view" : n === 1 ? "Tracking one hand" : "Tracking both hands";
    return `${who} at ${Math.round(orion.fps)} fps, using the ${s.profile} profile.`;
  });
  const extended = (h, f) => h.extended & (1 << f);
</script>

<header>
  <h1>Live</h1>
  <p class="muted">{sentence}</p>
</header>

<div class="grid">
  <section class="stage panel">
    <HandView />
    <div class="readouts">
      {#each orion.hands as h (h.side)}
        <div class="readout {h.side}">
          <h3>{h.side === "left" ? "Left hand" : "Right hand"}</h3>
          {#each [["Pinch", h.pinch], ["Grab", h.grab], ["Confidence", h.confidence]] as [label, v]}
            <div class="meter"><span>{label}</span><i style:--v={v}></i><b>{Math.round(v * 100)}</b></div>
          {/each}
          <div class="fingers" aria-label="Extended fingers">
            {#each FINGERS as name, f}<span class:on={extended(h, f)} title={name}>{name[0]}</span>{/each}
          </div>
        </div>
      {/each}
    </div>
    <p class="hint muted">Drag to orbit · scroll to zoom</p>
  </section>

  <aside class="panel side">
    <h2>Recent gestures</h2>
    <div class="scroll"><EventFeed /></div>
  </aside>

  <section class="panel irbox">
    <div class="irhead">
      <h2>Infrared cameras</h2>
      <div class="seg" role="group" aria-label="IR colours">
        <button class:on={palette === "night"} onclick={() => (palette = "night")}>Night</button>
        <button class:on={palette === "gray"} onclick={() => (palette = "gray")}>Raw</button>
      </div>
    </div>
    <IRView {palette} />
  </section>
</div>

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 18px; flex-wrap: wrap; }
  .grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; }
  .stage { position: relative; height: min(56vh, 560px); overflow: hidden; }
  .side { grid-row: span 2; padding: 16px; position: relative; min-height: 320px; }
  .side .scroll { position: absolute; inset: 52px 12px 12px 16px; overflow: auto; } /* never stretches the grid */
  .irbox { padding: 14px 16px 16px; display: grid; gap: 10px; }
  .irhead { display: flex; justify-content: space-between; align-items: center; }
  .seg { display: flex; border: 1px solid var(--line); border-radius: var(--r-sm); overflow: hidden; }
  .seg button { border: 0; border-radius: 0; background: none; color: var(--dust); padding: 4px 10px; }
  .seg button.on { background: var(--nebula-2); color: var(--star); }

  .readouts { position: absolute; top: 14px; left: 14px; display: flex; gap: 10px; pointer-events: none; }
  .readout { width: 190px; padding: 10px 12px; border-radius: var(--r-sm); background: #0a0e1fcc; backdrop-filter: blur(8px); border: 1px solid var(--line); border-top: 2px solid var(--hand); display: grid; gap: 5px; }
  .readout h3 { color: var(--hand); font-size: 13px; }
  .meter { display: grid; grid-template-columns: 72px 1fr 26px; align-items: center; gap: 8px; font-size: 12px; color: var(--dust); }
  .meter i { height: 4px; border-radius: 4px; background: linear-gradient(90deg, var(--hand) calc(var(--v) * 100%), var(--line) 0); }
  .meter b { font-weight: 500; color: var(--star); text-align: right; font-variant-numeric: tabular-nums; }
  .fingers { display: flex; gap: 4px; margin-top: 3px; }
  .fingers span { flex: 1; text-align: center; font-size: 11px; padding: 2px 0; border-radius: 4px; color: var(--dust); background: var(--nebula); }
  .fingers span.on { color: var(--void); background: var(--hand); font-weight: 600; }
  .hint { position: absolute; bottom: 10px; right: 14px; font-size: 11.5px; }

  @media (max-width: 1100px) {
    .grid { grid-template-columns: 1fr; }
    .side { grid-row: auto; height: 360px; }
  }
</style>
