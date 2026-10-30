<script>
  // OrionDo: edit the radial menu (the wheel) and how it behaves. Edits go to the draft, like every other page.
  import Switch from "../components/Switch.svelte";
  import MenuWheel from "../components/MenuWheel.svelte";
  import ItemInspector from "../components/ItemInspector.svelte";
  import Breadcrumb from "../components/Breadcrumb.svelte";
  import { RotateCcw } from "@lucide/svelte";
  import { orion, skinPreviewUrl } from "../lib/link.svelte.js";
  import {
    SKINS, weightOf, addItem, backAt, blankItem, canNest, clampPath, crumbs, isSubmenu, listAt, moveItem, removeItem, selectionAfterMove,
    selectionAfterRemove,
  } from "../lib/menu.js";

  const present = $derived(orion.gestures.some((g) => g.name === "oriondo"));
  const conf = () => ((orion.draft.gestures.oriondo ??= {}), orion.draft.gestures.oriondo); // reactive proxy, created on first edit
  // The menu being edited is the main one (`gestures.oriondo`) or a profile's own (`profiles.<name>.oriondo`); settings stay global.
  let scope = $state(""); // "" = the main menu, else a profile name
  const profiles = $derived(Object.keys(orion.draft?.profiles ?? {}));
  const m = $derived(scope ? orion.draft?.profiles?.[scope]?.oriondo : orion.draft?.gestures?.oriondo); // undefined: a profile without its own menu
  const mconf = () => (scope ? orion.draft.profiles[scope].oriondo : conf());
  $effect(() => { // a renamed or deleted profile
    if (scope && !profiles.includes(scope)) scope = "";
  });
  const pick = (name) => ((scope = name), (path = []), (sel = -1));
  const ownMenu = () => (orion.draft.profiles[scope].oriondo = { ...structuredClone($state.snapshot(orion.draft.gestures.oriondo ?? {})), items: structuredClone($state.snapshot(orion.draft.gestures.oriondo?.items ?? [])) });
  const dropMenu = () => confirm(`Delete ${scope}'s own menu? It will use the main menu again.`) && delete orion.draft.profiles[scope].oriondo;
  const list = () => (mconf().items ??= []);
  const root = $derived(m?.items ?? []);
  let path = $state([]); // indices of the submenus being edited; [] is the root menu
  const here = $derived(clampPath(root, path)); // a discarded draft, a reset or a conversion can remove the level under us
  const items = $derived(listAt(root, here) ?? []);
  const back = $derived(backAt(root, here));
  const trail = $derived(crumbs(root, here));
  const enabled = $derived(orion.draft?.gestures?.oriondo?.enabled ?? true);
  const shipped = $derived(scope ? orion.draft?.gestures?.oriondo?.items : orion.gestureDefaults.oriondo?.items); // what Reset restores
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
  function resize(a, b, wa, wb) {
    items[a].weight = wa;
    items[b].weight = wb;
  }
  const loadDefaults = () => ((mconf().items = structuredClone($state.snapshot(shipped))), goto([]));
  const menuModified = $derived(JSON.stringify($state.snapshot(root)) !== JSON.stringify($state.snapshot(shipped ?? [])));
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
  const skin = $derived(m?.skin ?? SKINS[0].id);
  const skinHue = $derived(SKINS.find((s) => s.id === skin)?.hue ?? SKINS[0].hue);
  const hue = $derived(m?.hue); // undefined: the skin's own colour
  // The thumbnails redraw for the menu being edited, a little after the last change (the slider fires on every pixel).
  let preview = $state({ labels: '["1","2","3","4"]' });
  $effect(() => {
    const labels = items.length ? items.map((i) => String(i.label ?? "")) : ["1", "2", "3", "4"];
    const next = { labels: JSON.stringify(labels), weights: JSON.stringify(items.map(weightOf)), ...(hue === undefined ? {} : { hue }), ...(invert ? { invert: 1 } : {}) };
    const t = setTimeout(() => (preview = next), 200);
    return () => clearTimeout(t);
  });
  const invert = $derived(m?.invert === true);
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
  {#if present && orion.draft && profiles.length}
    <label class="scope"><span class="muted">Menu for</span>
      <select value={scope} onchange={(e) => pick(e.target.value)}>
        <option value="">Main menu (all apps)</option>
        {#each profiles as p}<option value={p}>{p}{orion.draft.profiles[p].oriondo ? " · own menu" : ""}</option>{/each}
      </select>
    </label>
  {/if}
  {#if present && orion.draft}
    <label class="power"><Switch label="Enable OrionDo" checked={enabled} onchange={(on) => (conf().enabled = on)} /> {enabled ? "On" : "Off"}</label>
  {/if}
</header>

{#if !present}
  <p class="muted">This version of Orion has no OrionDo.</p>
{:else if orion.draft && scope && !m}
  <section class="panel box none">
    <h2>{scope} uses the main menu</h2>
    <p class="muted">
      {#if orion.draft.profiles[scope].exclusive}This profile is exclusive: until it has its own menu, OrionDo will not open in its app.
      {:else}While {scope}'s app is focused, OrionDo opens the main menu. Give it its own to change that.{/if}
    </p>
    <p><button onclick={ownMenu}>Give {scope} its own menu</button> <span class="muted">Starts as a copy of the main menu.</span></p>
  </section>
{:else if orion.draft}
  <div class="cols">
    <section class="panel wheel" class:off={!enabled}>
      <Breadcrumb crumbs={trail} onpick={goto} />
      <MenuWheel {items} {back} parentLabel={trail[trail.length - 1].label} selected={sel} onselect={(i) => (sel = i)} onmove={move}
                 onadd={add} onremove={remove} onenter={() => labelField?.focus()} onopen={open} onup={up}
                 onresize={resize} onequal={() => items.forEach((it) => delete it.weight)} />
      {#if here.length}<!-- the defaults replace the whole menu: offered at the root only -->
      {:else if !items.length && shipped?.length}
        <p class="load"><button onclick={loadDefaults}>Load {scope ? "the main menu" : "the default menu"}</button></p>
      {:else if shipped?.length}
        <p class="load"><button class="ghost" onclick={loadDefaults} disabled={!menuModified}><RotateCcw size={13} /> Reset menu to {scope ? "the main menu" : "defaults"}</button></p>
      {/if}
      {#if scope && !here.length}<p class="load"><button class="ghost danger" onclick={dropMenu}>Use the main menu instead</button></p>{/if}
    </section>
    <div class="side">
      <section class="panel box">
        <h2>{sel >= 0 ? `Slice ${sel + 1}` : "Slice"}</h2>
        <ItemInspector item={items[sel]} onremove={() => remove(sel)} onopen={() => open(sel)} canNest={canNest(here)}
                       bind:inputref={labelField} />
      </section>
      <section class="panel box look">
        <h2>Look</h2>
        <div class="skins" role="group" aria-label="Skin">
          {#each SKINS as s (s.id)}
            <button class:on={skin === s.id} aria-pressed={skin === s.id} onclick={() => (mconf().skin = s.id)} title="{s.label} · {s.note}">
              <span class="thumb"><img src={skinPreviewUrl(s.id, preview)} alt="" width="560" height="560" loading="lazy" /></span>
              <span>{s.label}</span>
            </button>
          {/each}
        </div>
        <label class="row">
          <span>Colour</span>
          <input type="range" min="0" max="359" step="1" class="hue" value={hue ?? skinHue} oninput={(e) => (mconf().hue = +e.target.value)} />
          <button class="ghost" onclick={() => delete mconf().hue} disabled={hue === undefined}>Reset</button>
        </label>
        <label class="row">
          <span>Text</span>
          <span class="inline"><Switch label="Invert text colour" checked={invert} onchange={(on) => (on ? (mconf().invert = true) : delete mconf().invert)} /> {invert ? "Inverted" : "Skin default"}</span>
        </label>
        <small class="muted">Colour tints the whole skin; shapes and contrast stay. Takes effect the next time the menu opens.</small>
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
  .scope { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .none { max-width: 560px; }
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
  .hue { background: linear-gradient(90deg, hsl(0 80% 55%), hsl(60 80% 55%), hsl(120 80% 55%), hsl(180 80% 55%), hsl(240 80% 55%), hsl(300 80% 55%), hsl(360 80% 55%)); height: 8px; border-radius: 4px; }
  .skins { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .skins button { display: grid; gap: 4px; padding: 4px; background: transparent; border: 1px solid var(--line); border-radius: 8px; font-size: 11.5px; color: var(--dust); }
  .skins button.on { border-color: var(--rigel); color: var(--star); background: #335e9e33; }
  .skins .thumb { display: block; aspect-ratio: 1; overflow: hidden; border-radius: 5px; }
  .skins img { width: 125%; max-width: none; margin: -12.5%; height: auto; display: block; } /* the pie fills the middle 80% of the window */
  .look .row { display: grid; grid-template-columns: 56px 1fr auto; align-items: center; gap: 10px; font-size: 12.5px; color: var(--dust); }
  .look .inline { grid-column: 2 / 4; display: flex; align-items: center; gap: 8px; }
  details { display: grid; gap: 12px; }
  summary { cursor: pointer; color: var(--dust); font-size: 12.5px; }
  details[open] summary { margin-bottom: 12px; }
</style>
