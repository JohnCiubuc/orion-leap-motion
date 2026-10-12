<script>
  // General settings (the [general] table of config.toml).
  import { FolderOpen, RotateCcw } from "@lucide/svelte";
  import Switch from "../components/Switch.svelte";
  import { orion, send } from "../lib/link.svelte.js";

  const g = $derived(orion.draft?.general);
</script>

<header>
  <h1>Settings</h1>
  <p class="muted">Stored in <code>~/.config/orion-renewal/config.toml</code>. Edits to that file apply live too.</p>
</header>

{#if g}
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
      <div><h3>Infrared preview rate</h3><p class="muted">Only streamed while the Live view is open.</p></div>
      <label class="num"><input type="range" min="5" max="60" step="5" bind:value={g.ir_fps} /> {g.ir_fps} fps</label>
    </div>
    <div class="row">
      <div><h3>Tracking source</h3><p class="muted">Demo generates synthetic hands for trying Orion without a device. Applies on restart.</p></div>
      <select bind:value={g.source}><option value="leap">Leap Motion</option><option value="demo">Demo</option></select>
    </div>
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
      <div><h3>Config folder</h3><p class="muted">Config, plugins and recorded shape templates.</p></div>
      <button onclick={() => send("reveal", { what: "config" })}><FolderOpen size={15} /> Open folder</button>
    </div>
  </div>
{/if}

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 22px; flex-wrap: wrap; }
  .list { max-width: 820px; }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 14px 18px; border-bottom: 1px solid var(--line); }
  .row:last-child { border-bottom: 0; }
  .row p { font-size: 13px; margin-top: 2px; max-width: 60ch; }
  .dim { opacity: .5; }
  .num { display: flex; align-items: center; gap: 8px; color: var(--dust); white-space: nowrap; }
  .num input[type="number"] { width: 80px; }
  .num input[type="range"] { width: 160px; }
</style>
