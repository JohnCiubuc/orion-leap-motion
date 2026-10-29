<script>
  // Settings: the [general] and [overlay] tables of config.toml, plus device and input checks.
  import { FolderOpen, RotateCcw, MousePointer2, Eye } from "@lucide/svelte";
  import Switch from "../components/Switch.svelte";
  import { orion, send } from "../lib/link.svelte.js";

  const g = $derived(orion.draft?.general);
  const o = $derived(orion.draft?.overlay);
  const w = $derived(orion.draft?.webcam);
  const s = $derived(orion.status);
</script>

<header>
  <h1>Settings</h1>
  <p class="muted">Stored in <code>~/.config/orion-renewal/config.toml</code>. Edits to that file apply live too.</p>
</header>

{#if g && o}
  <!-- ── Recognition ── -->
  <h2>Recognition</h2>
  <div class="panel list">
    <div class="row">
      <div><h3>Require engage gesture</h3>
        <p class="muted">Turn on if gestures fire by accident. Hold an open palm toward the screen to arm the next gesture.</p></div>
      <Switch bind:checked={g.engage_required} label="Require engage gesture" />
    </div>
    <div class="row" class:dim={!g.engage_required}>
      <div><h3>Engage window</h3><p class="muted">How long after engaging a gesture can still fire.</p></div>
      <label class="num"><input type="number" min="0.5" max="10" step="0.5" bind:value={g.engage_window} /> s</label>
    </div>
    <div class="row">
      <div><h3>Tracking source</h3><p class="muted">Demo generates synthetic hands for trying Orion without a device. Applies on restart.</p></div>
      <select bind:value={g.source}><option value="leap">Leap Motion</option><option value="webcam">Webcam</option><option value="demo">Demo</option></select>
    </div>
    {#if g.source === "webcam" && w}
      <div class="row">
        <div><h3>Camera</h3>
          <p class="muted">Auto picks the first camera that works. Choose one here if it picks the wrong one.
            {#if s.error}<br /><span class="warn">{s.error}</span>{/if}</p></div>
        <select bind:value={w.device}>
          <option value="auto">Auto-detect</option>
          {#each s.cameras ?? [] as c (c.path)}<option value={c.path}>{c.name} ({c.path})</option>{/each}
        </select>
      </div>
    {/if}
  </div>

  <!-- ── Overlay ── -->
  <h2>Gesture overlay</h2>
  <div class="panel list">
    <div class="row">
      <div><h3>Show recognised gestures on screen</h3>
        <p class="muted">A translucent card in a corner of the focused monitor. It never takes focus and clicks pass through it.
          {#if s.overlay && s.overlay !== "on" && s.overlay !== "off"}<br /><span class="warn">Overlay {s.overlay}</span>{/if}</p></div>
      <Switch bind:checked={o.enabled} label="Show overlay" />
    </div>
    <div class="row" class:dim={!o.enabled}>
      <div><h3>Precision ring</h3><p class="muted">A ring around the cursor while the pointer is in precision mode.</p></div>
      <Switch bind:checked={o.precision_ring} label="Precision ring" />
    </div>
    <div class="row" class:dim={!o.enabled}>
      <div><h3>Opacity</h3></div>
      <label class="num"><input type="range" min="0.2" max="1" step="0.05" bind:value={o.opacity} /> {Math.round(o.opacity * 100)} %</label>
    </div>
    <div class="row" class:dim={!o.enabled}>
      <div><h3>Duration</h3><p class="muted">How long each card stays before fading.</p></div>
      <label class="num"><input type="number" min="0.5" max="10" step="0.1" bind:value={o.seconds} /> s</label>
    </div>
    <div class="row" class:dim={!o.enabled}>
      <div><h3>Corner</h3></div>
      <select bind:value={o.corner}>
        <option value="top-right">Top right</option><option value="top-left">Top left</option>
        <option value="bottom-right">Bottom right</option><option value="bottom-left">Bottom left</option>
      </select>
    </div>
    <div class="row" class:dim={!o.enabled}>
      <div><h3>Include unbound gestures</h3><p class="muted">Also show gestures that have no action in the current profile.</p></div>
      <Switch bind:checked={o.show_unbound} label="Include unbound gestures" />
    </div>
    <div class="row" class:dim={!o.enabled}>
      <div><h3>Preview</h3><p class="muted">Shows a sample card. Save first to preview new settings.</p></div>
      <button onclick={() => send("overlay_test")} disabled={s.overlay !== "on"}><Eye size={15} /> Show sample</button>
    </div>
  </div>

  <!-- ── Controller ── -->
  <h2>Controller</h2>
  <div class="panel list">
    <div class="row">
      <div><h3>Restart controller</h3>
        <p class="muted">Wakes a controller that stopped sending frames: unpauses tracking and resets the USB device, like replugging it.</p></div>
      <button onclick={() => send("restart_device")}><RotateCcw size={15} /> Restart controller</button>
    </div>
    <div class="row">
      <div><h3>Restart tracking service</h3>
        <p class="muted">If restarting the controller doesn't help. Asks for your password.</p></div>
      <button onclick={() => send("restart_device", { service: true })}><RotateCcw size={15} /> Restart service</button>
    </div>
    <div class="row">
      <div><h3>Wake automatically</h3>
        <p class="muted">Restart the controller when it sends no frames for this long. At most once a minute; 0 turns it off.</p></div>
      <label class="num"><input type="number" min="0" max="300" step="5" bind:value={g.auto_wake} /> s</label>
    </div>
    <div class="row">
      <div><h3>Preferred hand</h3>
        <p class="muted">A hand coming into view counts as this side until the tracker has been sure otherwise for a moment. Stops left and right flipping as a hand enters.</p></div>
      <select bind:value={g.preferred_hand}><option value="left">Left</option><option value="right">Right</option><option value="none">No preference</option></select>
    </div>
    <div class="row">
      <div><h3>Infrared preview rate</h3><p class="muted">Only streamed while the Live view is open.</p></div>
      <label class="num"><input type="range" min="5" max="60" step="5" bind:value={g.ir_fps} /> {g.ir_fps} fps</label>
    </div>
  </div>

  <!-- ── Input emulation ── -->
  <h2>Input emulation</h2>
  <div class="panel list">
    <div class="row">
      <div><h3>Virtual mouse and keyboard</h3>
        <p class="muted">{#if s.input === "ready"}<span class="good">Ready.</span> Use the test to check the cursor moves without involving tracking.
          {:else}<span class="warn">{s.input ?? "Unknown"}</span>{/if}</p></div>
      <button onclick={() => send("test_action", { action: "input.test_pointer" })} disabled={s.input !== "ready"}>
        <MousePointer2 size={15} /> Test mouse</button>
    </div>
    <div class="row">
      <div><h3>Config folder</h3><p class="muted">Config, plugins and recorded shape templates.</p></div>
      <button onclick={() => send("reveal", { what: "config" })}><FolderOpen size={15} /> Open folder</button>
    </div>
  </div>
{/if}

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 22px; flex-wrap: wrap; }
  h2 { margin: 0 0 10px; }
  .list { max-width: 820px; margin-bottom: 26px; overflow: hidden; }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 14px 18px; border-bottom: 1px solid var(--line); }
  .row:last-child { border-bottom: 0; }
  .row p { font-size: 13px; margin-top: 2px; max-width: 60ch; }
  .dim { opacity: .5; }
  .warn { color: var(--warn); }
  .good { color: var(--ok); }
  .num { display: flex; align-items: center; gap: 8px; color: var(--dust); white-space: nowrap; }
  .num input[type="number"] { width: 80px; }
  .num input[type="range"] { width: 160px; }
</style>
