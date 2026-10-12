<script>
  // Gesture library: enable/disable, tune parameters, record new path shapes.
  import { ChevronDown } from "@lucide/svelte";
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
  const conf = (name) => (orion.draft.gestures[name] ??= {});
  const enabled = (name) => orion.draft?.gestures?.[name]?.enabled ?? true;
  const value = (g, k) => orion.draft?.gestures?.[g.name]?.[k] ?? g.params[k][0];
  const step = ([d, lo, hi]) => (Number.isInteger(d) && Number.isInteger(hi) && hi - lo >= 10 ? 1 : (hi - lo) / 100);
</script>

<header>
  <h1>Gestures</h1>
  <p class="muted">{orion.gestures.length} gestures loaded. Changes apply when you save.</p>
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
                    </label>
                  {/each}
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
  .params label { display: grid; grid-template-columns: 96px 1fr 44px; align-items: center; gap: 10px; font-size: 12.5px; color: var(--dust); }
  .params b { color: var(--star); font-weight: 500; text-align: right; font-variant-numeric: tabular-nums; }
  .record { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: var(--void); flex-wrap: wrap; }
  .record p { flex: 1 1 100%; font-size: 13px; }
  .record input { width: 220px; }
</style>
