<script>
  // OrionDo: edit the radial menu (the wheel) and how it behaves. Edits go to the draft, like every other page.
  import Switch from "../components/Switch.svelte";
  import MenuWheel from "../components/MenuWheel.svelte";
  import ItemInspector from "../components/ItemInspector.svelte";
  import Breadcrumb from "../components/Breadcrumb.svelte";
  import { RotateCcw } from "@lucide/svelte";
  import { orion } from "../lib/link.svelte.js";
  import {
    addItem, backAt, blankItem, canNest, clampPath, crumbs, isSubmenu, listAt, moveItem, removeItem, selectionAfterMove,
    selectionAfterRemove,
  } from "../lib/menu.js";

  const present = $derived(orion.gestures.some((g) => g.name === "oriondo"));
  const conf = () => ((orion.draft.gestures.oriondo ??= {}), orion.draft.gestures.oriondo); // reactive proxy, created on first edit
  const list = () => (conf().items ??= []);
  const root = $derived(orion.draft?.gestures?.oriondo?.items ?? []);
  let path = $state([]); // indices of the submenus being edited; [] is the root menu
  const here = $derived(clampPath(root, path)); // a discarded draft, a reset or a conversion can remove the level under us
  const items = $derived(listAt(root, here) ?? []);
  const back = $derived(backAt(root, here));
  const trail = $derived(crumbs(root, here));
  const enabled = $derived(orion.draft?.gestures?.oriondo?.enabled ?? true);
  const shipped = $derived(orion.gestureDefaults.oriondo?.items);
  let sel = $state(-1);
  $effect(() => { // a discarded draft or a reload can shorten the list under the selection
    if (sel >= items.length) sel = items.length - 1;
  });
  $effect(() => {
    if (here.length !== path.length) path = here;
  });
  const goto = (p) => ((path = p), (sel = -1));
  const open = (i) => isSubmenu(items[i]) && goto([...here, i]);
  const up = () => here.length && goto(here.slice(0, -1));

  function add() {
    const l = list(), at = sel >= 0 ? sel + 1 : listAt(l, here).length;
    if (addItem(l, here, blankItem(l, here), at)) sel = at;
  }
  function remove(i) {
    removeItem(list(), here, i);
    sel = selectionAfterRemove(sel, i, listAt(list(), here).length);
  }
  function move(from, to) {
    moveItem(list(), here, from, to);
    sel = selectionAfterMove(sel, from, to);
  }
  const loadDefaults = () => ((conf().items = structuredClone($state.snapshot(shipped))), goto([]));
  const menuModified = $derived(JSON.stringify($state.snapshot(items)) !== JSON.stringify($state.snapshot(shipped ?? [])));
  let labelField = $state(); // the inspector's label input, so Enter on a slice can jump to it

  // ── Settings: ranges, choices and defaults come from the engine's gesture metadata ──
  const params = $derived(orion.gestures.find((g) => g.name === "oriondo")?.params ?? {});
  const defaults = $derived(orion.gestureDefaults.oriondo ?? {});
  const BASIC = ["trigger", "deadzone", "pull"], ADVANCED = ["lost", "cooldown", "tap_trigger", "tap_still"];
  const HELP = {
    trigger: "The pose that opens the menu.",
    deadzone: "Distance (mm) from the centre before a slice is hovered.",
    pull: "Distance (mm) to pull out to fire the hovered slice.",
    lost: "Seconds without the hand before the menu closes.",
    cooldown: "Pause (s) after the menu closes before it can reopen.",
    tap_trigger: "How far (mm) a fingertip must move against the palm to count as a tap (closes the menu at the centre).",
    tap_still: "The palm must be slower than this (mm/s) for a finger move to count as a tap.",
  };
  const title = (n) => n.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const value = (k) => orion.draft?.gestures?.oriondo?.[k] ?? params[k]?.[0];
  const step = (range) => (range.every(Number.isInteger) ? 1 : 0.05); // on the slider's grid, so a default like 1.5 shows as 1.5
  const settingsModified = $derived(Object.keys(params).some((k) => value(k) !== (defaults[k] ?? params[k][0])));
  function resetSettings() {
    for (const k of Object.keys(params)) {
      if (k in defaults) conf()[k] = defaults[k];
      else delete conf()[k]; // not in the shipped config: the engine's own default applies
    }
  }
</script>

{#snippet control(k)}
  {@const range = params[k]}
  {#if range}
    <label>
      <span>{title(k)}</span>
      {#if Array.isArray(range[1])}<!-- choice param → dropdown -->
        <select value={value(k)} onchange={(e) => (conf()[k] = e.target.value)}>
          {#each range[1] as c}<option>{c}</option>{/each}
        </select><b></b>
      {:else}
        <input type="range" min={range[1]} max={range[2]} step={step(range)} value={value(k)}
               oninput={(e) => (conf()[k] = +e.target.value)} />
        <b>{+(+value(k)).toFixed(2)}</b>
      {/if}
      <small>{HELP[k]}</small>
    </label>
  {/if}
{/snippet}

<header>
  <h1>OrionDo</h1>
  <p class="muted">A radial menu you steer with your fingertip. Pose to open, move to hover a slice, pull to fire it.</p>
  {#if present && orion.draft}
    <label class="power"><Switch label="Enable OrionDo" checked={enabled} onchange={(on) => (conf().enabled = on)} /> {enabled ? "On" : "Off"}</label>
  {/if}
</header>

{#if !present}
  <p class="muted">This version of Orion has no OrionDo.</p>
{:else if orion.draft}
  <div class="cols">
    <section class="panel wheel" class:off={!enabled}>
      <Breadcrumb crumbs={trail} onpick={goto} />
      <MenuWheel {items} {back} parentLabel={trail[trail.length - 1].label} selected={sel} onselect={(i) => (sel = i)} onmove={move}
                 onadd={add} onremove={remove} onenter={() => labelField?.focus()} onopen={open} onup={up} />
      {#if !items.length && shipped?.length}
        <p class="load"><button onclick={loadDefaults}>Load the default menu</button></p>
      {:else if shipped?.length}
        <p class="load"><button class="ghost" onclick={loadDefaults} disabled={!menuModified}><RotateCcw size={13} /> Reset menu to defaults</button></p>
      {/if}
    </section>
    <div class="side">
      <section class="panel box">
        <h2>{sel >= 0 ? `Slice ${sel + 1}` : "Slice"}</h2>
        <ItemInspector item={items[sel]} onremove={() => remove(sel)} onopen={() => open(sel)} canNest={canNest(here)}
                       bind:inputref={labelField} />
      </section>
      <section class="panel box params">
        <div class="head">
          <h2>Settings</h2>
          <button class="ghost" onclick={resetSettings} disabled={!settingsModified}><RotateCcw size={13} /> Reset</button>
        </div>
        {#each BASIC as k}{@render control(k)}{/each}
        <details>
          <summary>Advanced</summary>
          {#each ADVANCED as k}{@render control(k)}{/each}
        </details>
      </section>
    </div>
  </div>
{/if}

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 22px; flex-wrap: wrap; }
  .power { margin-left: auto; display: flex; align-items: center; gap: 8px; color: var(--dust); }
  .cols { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 18px; max-width: 1100px; align-items: start; }
  @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
  .wheel { padding: 22px 18px 16px; }
  .wheel.off { opacity: .5; }
  .load { text-align: center; margin-top: 10px; }
  .side { display: grid; gap: 18px; }
  .box { padding: 16px; display: grid; gap: 12px; }
  .params .head { display: flex; align-items: center; justify-content: space-between; }
  .params label { display: grid; grid-template-columns: 78px 1fr 40px; align-items: center; gap: 4px 10px; font-size: 12.5px; color: var(--dust); }
  .params small { grid-column: 1 / -1; font-size: 11.5px; line-height: 1.35; color: #8a93b8b0; }
  .params b { color: var(--star); font-weight: 500; text-align: right; font-variant-numeric: tabular-nums; }
  details { display: grid; gap: 12px; }
  summary { cursor: pointer; color: var(--dust); font-size: 12.5px; }
  details[open] summary { margin-bottom: 12px; }
</style>
