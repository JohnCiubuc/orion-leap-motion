<script>
  // Gesture library: enable/disable, tune parameters, record new path shapes.
  import { ChevronDown, RotateCcw } from "@lucide/svelte";
  import Switch from "../components/Switch.svelte";
  import { orion, send } from "../lib/link.svelte.js";

  const FAMILIES = [
    ["pose", "Poses", "Hand shapes held for a moment."],
    ["motion", "Motions", "Quick movements, recognised over a short time window."],
    ["path", "Shapes", "Draw in the air with your index finger, then relax your hand."],
    ["joystick", "Pinch & hold", "Pinch or make a fist, then move. Each step of distance fires once and becomes the new starting point."],
    ["continuous", "Continuous", "Stream a value while active, for knobs, zoom and pointers."],
  ];
  let open = $state({});
  let shapeName = $state("");
  const title = (n) => n.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const conf = (name) => ((orion.draft.gestures[name] ??= {}), orion.draft.gestures[name]); // reactive proxy, not the raw {}
  const enabled = (name) => orion.draft?.gestures?.[name]?.enabled ?? true;
  // One-line explanations for tuning params (shown under each control). Plugins' own params show without one.
  const HELP = {
    hold: "Seconds the pose must be held before it fires.",
    still: "Max hand speed (mm/s) that still counts as holding still; moving faster cancels it.",
    pinch: "How tightly thumb and index must touch (0 = open, 1 = touching).",
    grab: "How closed the hand must be (0 = open, 1 = tight fist).",
    strength: "How firm the pinch or grip must be to count (0–1).",
    min_up: "How straight up the thumb must point (1 = vertical).",
    min_down: "How straight down the thumb must point (1 = vertical).",
    facing: "How squarely the palm must face the screen (1 = straight on).",
    window: "Time span (s) the movement is measured over.",
    cooldown: "Pause (s) after firing before it can fire again.",
    distance: "How far (mm) the hand must travel.",
    open_hand: "Only count it with an open hand.",
    threshold: "How alike the movement must be to the pattern (higher = stricter).",
    depth: "How far (mm) the fingertip must dip.",
    min_length: "Shortest stroke (mm) that counts as a drawing.",
    step: "Distance (mm) per event; the start point resets after each one.",
    axis: "What counts as up/down: raising, pushing away, or both.",
    track: "Which part of the hand steers the cursor.",
    steady: "Smoothing when still: lower = steadier but slower to start.",
    responsive: "How quickly smoothing drops when you move fast: higher = less lag.",
    max_grab: "Above this grip the cursor stops (close your hand to let go).",
    precision: "Cursor travel per mm of hand movement once the hand settles (1 = off).",
    dwell: "How long (s) the hand must stay slow before precision starts.",
    enter_speed: "Hand speed (mm/s) below which precision can start.",
    exit_speed: "Hand speed (mm/s) above which precision ends and the cursor follows the hand.",
    radius: "Distance (mm) from where precision started at which movement is 1:1 again.",
    edge: "Distance (mm) from the view's limits where precision is off, so the screen edges always reach.",
    rest: "Hand tremor (mm) ignored while precise.",
    glide: "Time (s) for the cursor to glide back onto the hand after precision.",
    tap_hold: "How long (s) the cursor holds after a finger tap.",
    tap_trigger: "How far (mm) a fingertip must move against the palm to count as a tap.",
    tap_still: "The palm must be slower than this (mm/s) for a finger move to count as a tap.",
  };
  const defaults = (name) => structuredClone($state.snapshot(orion.gestureDefaults[name] ?? {}));
  const reset = (name) => (orion.draft.gestures[name] = defaults(name));
  const modified = (name) => JSON.stringify(orion.draft?.gestures?.[name] ?? {}) !== JSON.stringify(orion.gestureDefaults[name] ?? {});
  const resetAll = () => {
    if (!confirm("Reset every gesture to its default settings? Takes effect when you save.")) return;
    for (const g of orion.gestures) if (modified(g.name)) reset(g.name);
  };
  const value = (g, k) => orion.draft?.gestures?.[g.name]?.[k] ?? g.params[k][0];
  const step = ([d, lo, hi]) => (Number.isInteger(d) && Number.isInteger(hi) && hi - lo >= 10 ? 1 : (hi - lo) / 100);
</script>

<header>
  <h1>Gestures</h1>
  <p class="muted">{orion.gestures.length} gestures loaded. Changes apply when you save.</p>
  <button class="ghost reset-all" onclick={resetAll} disabled={!orion.gestures.some((g) => modified(g.name))}>
    <RotateCcw size={14} /> Reset all to defaults
  </button>
</header>

{#if orion.draft}
  {#each FAMILIES as [fam, name, blurb]}
    {@const list = orion.gestures.filter((g) => g.family === fam)}
    {#if list.length}
      <section>
        <div class="famhead"><h2>{name}</h2><p class="muted">{blurb}</p></div>
        <div class="list panel">
          {#each list as g (g.name)}
            <div class="row" class:off={!enabled(g.name)}>
              {#key orion.flash[g.name]}<span class="pulse" class:fired={orion.flash[g.name]}></span>{/key}
              <div class="main">
                <div class="line">
                  <h3>{title(g.name)}</h3>
                  <div class="events">{#each g.events as e}<code>{e}</code>{/each}</div>
                </div>
                <p class="muted doc">{g.doc.split("\n")[0]}</p>
              </div>
              {#if Object.keys(g.params).length}
                <button class="ghost" aria-expanded={!!open[g.name]} onclick={() => (open[g.name] = !open[g.name])}>
                  Tune <ChevronDown size={14} style="rotate: {open[g.name] ? 180 : 0}deg" />
                </button>
              {/if}
              <Switch label="Enable {g.name}" checked={enabled(g.name)} onchange={(on) => (conf(g.name).enabled = on)} />
              {#if open[g.name]}
                <div class="params">
                  {#each Object.entries(g.params) as [k, range]}
                    <label>
                      <span>{title(k)}</span>
                      {#if Array.isArray(range[1])}<!-- choice param → dropdown -->
                        <select value={value(g, k)} onchange={(e) => (conf(g.name)[k] = e.target.value)}>
                          {#each range[1] as c}<option>{c}</option>{/each}
                        </select><b></b>
                      {:else if range[1] === 0 && range[2] === 1 && Number.isInteger(range[0])}<!-- 0/1 param → toggle -->
                        <Switch label={k} checked={!!value(g, k)} onchange={(on) => (conf(g.name)[k] = +on)} /><b></b>
                      {:else}
                        <input type="range" min={range[1]} max={range[2]} step={step(range)} value={value(g, k)}
                               oninput={(e) => (conf(g.name)[k] = +e.target.value)} />
                        <b>{+(+value(g, k)).toFixed(2)}</b>
                      {/if}
                      {#if HELP[k]}<small>{HELP[k]}</small>{/if}
                    </label>
                  {/each}
                  <button class="ghost reset" onclick={() => reset(g.name)} disabled={!modified(g.name)}>
                    <RotateCcw size={13} /> Reset to defaults
                  </button>
                </div>
              {/if}
            </div>
          {/each}
          {#if fam === "path"}
            <form class="record" onsubmit={(e) => (e.preventDefault(), shapeName && send("capture", { name: shapeName }))}>
              {#if orion.status.capture}
                <p><b>Draw “{orion.status.capture}” now.</b> <span class="muted">Point with your index finger, trace the shape, then relax.</span></p>
              {:else}
                <p class="muted">Teach a new shape: name it, then draw it once over the device.</p>
                <input type="text" placeholder="Shape name, e.g. heart" bind:value={shapeName} pattern="[a-z0-9_]+" />
                <button type="submit" disabled={!shapeName}>Record shape</button>
              {/if}
            </form>
          {/if}
        </div>
      </section>
    {/if}
  {/each}
{/if}

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 22px; }
  .reset-all { margin-left: auto; }
  .reset { grid-column: 1 / -1; justify-self: start; }
  section { margin-bottom: 26px; max-width: 980px; }
  .famhead { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; }
  .list { overflow: hidden; }
  .row { display: grid; grid-template-columns: 10px 1fr auto auto; align-items: center; gap: 12px 14px; padding: 12px 16px; border-bottom: 1px solid var(--line); }
  .row:last-child { border-bottom: 0; }
  .row.off .main { opacity: .45; }
  .line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .events { display: flex; gap: 5px; flex-wrap: wrap; }
  .events code { color: var(--dust); background: var(--void); padding: 0 6px; border-radius: 4px; font-size: 11.5px; }
  .doc { font-size: 13px; margin-top: 2px; }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--line); }
  .pulse.fired { animation: fire 1.4s ease-out; }
  @keyframes fire { from { background: var(--rigel); box-shadow: 0 0 12px var(--rigel); } to { background: var(--line); box-shadow: none; } }
  .params { grid-column: 2 / -1; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 8px 24px; padding: 4px 0 4px; }
  .params label { display: grid; grid-template-columns: 96px 1fr 44px; align-items: center; gap: 4px 10px; font-size: 12.5px; color: var(--dust); align-self: start; }
  .params small { grid-column: 1 / -1; font-size: 11.5px; line-height: 1.35; color: #8a93b8b0; }
  .params b { color: var(--star); font-weight: 500; text-align: right; font-variant-numeric: tabular-nums; }
  .record { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: var(--void); flex-wrap: wrap; }
  .record p { flex: 1 1 100%; font-size: 13px; }
  .record input { width: 220px; }
</style>
