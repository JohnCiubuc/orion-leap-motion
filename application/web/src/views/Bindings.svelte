<script>
  // Bindings editor: gesture → action (+ arguments), grouped by profile or mode.
  import { Plus, Trash2, Zap, Copy, GripVertical, Snowflake } from "@lucide/svelte";
  import { flip } from "svelte/animate";
  import Switch from "../components/Switch.svelte";
  import ArgsEditor from "../components/ArgsEditor.svelte";
  import { orion, send, gestureEvents, actionMeta } from "../lib/link.svelte.js";

  const scopes = $derived(orion.draft ? [
    { key: "default", label: "Default", kind: "profile" },
    ...Object.keys(orion.draft.profiles).map((p) => ({ key: p, label: p, kind: "profile" })),
    ...Object.keys(orion.draft.modes).map((m) => ({ key: m, label: m.replace(/_/g, " "), kind: "mode" })),
  ] : []);
  let scope = $state("default");
  const cur = $derived(scopes.find((s) => s.key === scope) ?? scopes[0]);
  const inScope = (b) => cur.kind === "mode" ? b.mode === cur.key
    : !b.mode && (b.profile ?? "default") === cur.key;
  const rows = $derived(orion.draft ? orion.draft.bindings.map((b, i) => [b, i]).filter(([b]) => inScope(b)) : []);
  const active = (s) => (s.kind === "mode" ? orion.status.modes?.includes(s.key) : orion.status.profile === s.key);

  // ── Create: blank binding in this tab, inserted at `at` (global index; default = end) ──
  function blank() {
    const b = { gesture: gestureEvents()[0], action: "notify", args: {} };
    if (cur.kind === "mode") b.mode = cur.key;
    else if (cur.key !== "default") b.profile = cur.key;
    return b;
  }
  const insert = (at, b) => orion.draft.bindings.splice(at, 0, b);
  const duplicate = (i) => insert(i + 1, structuredClone($state.snapshot(orion.draft.bindings[i])));

  // ── Reorder: drag by the grip, or Alt+↑/↓ on it. Order is visual (and the run order for one gesture). ──
  const ids = new WeakMap();
  let nextId = 0;
  const idOf = (b) => ids.get(b) ?? (ids.set(b, ++nextId), nextId);
  let armed = $state(-1), dragging = $state(-1), drop = $state(null); // drop = { i, after }

  function move(from, target, after) {
    const list = orion.draft.bindings;
    let to = after ? target + 1 : target;
    if (from === to || from + 1 === to) return;
    const [b] = list.splice(from, 1);
    list.splice(from < to ? to - 1 : to, 0, b);
  }
  function overRow(e, i) {
    if (dragging < 0) return;
    e.preventDefault();
    const r = e.currentTarget.getBoundingClientRect();
    drop = { i, after: e.clientY > r.top + r.height / 2 };
  }
  function endDrag() {
    if (dragging >= 0 && drop) move(dragging, drop.i, drop.after);
    armed = dragging = -1;
    drop = null;
  }
  function nudge(e, k) {
    const dir = { ArrowUp: -1, ArrowDown: 1 }[e.key];
    const other = rows[k + dir];
    if (!dir || !other) return;
    e.preventDefault();
    move(rows[k][1], other[1], dir > 0);
  }

  function setAction(b, name) {
    b.action = name;
    b.args = {}; // start from the new action's defaults
  }
</script>

<header>
  <h1>Bindings</h1>
  <p class="muted">What each gesture does. App profiles override the default bindings while that app is focused.</p>
</header>

<div class="tabs" role="tablist">
  {#each scopes as s (s.key)}
    <button role="tab" aria-selected={s.key === cur?.key} class:on={s.key === cur?.key} onclick={() => (scope = s.key)}>
      {s.label}{#if s.kind === "mode"}<span class="muted"> mode</span>{/if}
      {#if active(s)}<i class="live" title="Active now"></i>{/if}
    </button>
  {/each}
</div>

{#if cur}
  <div class="table panel">
    <div class="head muted"><span></span><span>Gesture</span><span>Hand</span><span>Action</span><span>Settings</span><span></span></div>
    {#each rows as [b, i], k (idOf(b))}
      {@const meta = actionMeta(b.action)}
      <div class="row" class:dragging={dragging === i} class:drop-before={drop?.i === i && !drop.after}
           class:drop-after={drop?.i === i && drop.after} animate:flip={{ duration: 160 }}
           draggable={armed === i} ondragstart={() => (dragging = i)} ondragover={(e) => overRow(e, i)}
           ondrop={(e) => (e.preventDefault(), endDrag())} ondragend={endDrag}>
        <button class="grip ghost" aria-label="Drag to reorder (Alt+↑/↓)" title="Drag to reorder"
                onpointerdown={() => (armed = i)} onpointerup={() => dragging < 0 && (armed = -1)}
                onkeydown={(e) => e.altKey && nudge(e, k)}><GripVertical size={15} /></button>
        <div class="gcol">
          <select bind:value={b.gesture} aria-label="Gesture">
            {#each orion.gestures as g}
              <optgroup label={g.name}>{#each g.events as e}<option value={e}>{e}</option>{/each}</optgroup>
            {/each}
          </select>
          {#if cur.kind === "mode" && b.gesture !== "pointer"}<!-- only meaningful for gestures other than the cursor itself -->
            <label class="freeze" title="While this gesture is in progress the air-mouse cursor stays where it is">
              <Switch checked={!!b.freeze_pointer} label="Freeze cursor" onchange={(on) => (b.freeze_pointer = on || undefined)} />
              <Snowflake size={13} /> Freeze cursor
            </label>
          {/if}
        </div>
        <select value={b.hand ?? ""} onchange={(e) => (b.hand = e.target.value || undefined)} aria-label="Hand">
          <option value="">Either</option><option value="left">Left</option><option value="right">Right</option>
        </select>
        <div>
          <select value={b.action} onchange={(e) => setAction(b, e.target.value)} aria-label="Action">
            {#each orion.actions as a}<option value={a.name}>{a.name}</option>{/each}
          </select>
          {#if meta}<p class="muted doc">{meta.doc}</p>{:else}<p class="bad doc">Unknown action — is its plugin loaded?</p>{/if}
        </div>
        <ArgsEditor item={b} />
        <div class="tools">
          <button class="ghost" title="Run this action now" onclick={() => send("test_action", { action: b.action, args: $state.snapshot(b.args ?? {}) })}><Zap size={15} /></button>
          <button class="ghost danger" title="Remove binding" onclick={() => orion.draft.bindings.splice(i, 1)}><Trash2 size={15} /></button>
        </div>

        <!-- Hover the seam below a row to insert there -->
        {#if dragging < 0}
          <div class="seam">
            <span class="line"></span>
            <button onclick={() => insert(i + 1, blank())}><Plus size={13} /> New</button>
            <button onclick={() => duplicate(i)} title="Copy the binding above"><Copy size={13} /> Duplicate</button>
            <span class="line"></span>
          </div>
        {/if}
      </div>
    {:else}
      <div class="empty">
        <p class="muted">No bindings here yet. Gestures fall back to the default profile.</p>
        <button onclick={() => insert(orion.draft.bindings.length, blank())}><Plus size={15} /> Add binding</button>
      </div>
    {/each}
  </div>
{/if}

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 18px; flex-wrap: wrap; }
  .tabs { display: flex; gap: 4px; margin-bottom: 12px; flex-wrap: wrap; }
  .tabs button { background: none; border-color: transparent; color: var(--dust); text-transform: capitalize; }
  .tabs button.on { background: var(--nebula-2); border-color: var(--line); color: var(--star); }
  .live { width: 6px; height: 6px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 6px var(--ok); }
  .table { max-width: 1200px; }
  .head, .row { display: grid; grid-template-columns: 22px 190px 92px 230px 1fr 74px; gap: 14px; padding: 10px 16px 10px 8px; align-items: start; }
  .head { font-size: 12px; border-bottom: 1px solid var(--line); }
  .row { border-bottom: 1px solid var(--line); position: relative; background: var(--nebula); }
  .row:last-child { border-bottom: 0; border-radius: 0 0 var(--r-lg) var(--r-lg); }
  .row select, .row input { width: 100%; }
  .row.dragging { opacity: .4; }
  .row.drop-before { box-shadow: inset 0 2px 0 var(--rigel); }
  .row.drop-after { box-shadow: inset 0 -2px 0 var(--rigel); }
  .grip { padding: 6px 2px; cursor: grab; color: var(--line); }
  .row:hover .grip { color: var(--dust); }
  .grip:active { cursor: grabbing; }
  .gcol { display: grid; gap: 8px; }
  .freeze { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--dust); }
  .doc { font-size: 12px; margin-top: 4px; line-height: 1.4; }
  .bad { color: var(--bad); }
  .tools { display: flex; justify-content: flex-end; }
  .tools button { padding: 6px 7px; }
  .empty { padding: 18px 16px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }

  /* Insert seam: an invisible strip over the border between two rows; hovering reveals it */
  .seam { position: absolute; left: 0; right: 0; bottom: -11px; height: 22px; z-index: 3;
          display: flex; align-items: center; gap: 8px; padding: 0 16px; opacity: 0; transition: opacity .12s; }
  .seam:hover, .seam:focus-within { opacity: 1; }
  .seam .line { flex: 1; height: 1px; background: var(--rigel); opacity: .6; }
  .seam button { padding: 2px 9px; font-size: 12px; border-radius: 99px; background: var(--void); border-color: var(--rigel); color: var(--rigel); }
  .row:last-child .seam { bottom: -11px; }
</style>
