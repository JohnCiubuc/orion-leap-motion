<script>
  // The OrionDo wheel: draws the menu like the on-screen pie and lets you select, reorder (drag or Alt+arrows),
  // add and remove slices. It holds no menu data; the page owns it and passes callbacks.
  import { tick, untrack } from "svelte";
  import { cubicOut } from "svelte/easing";
  import { SvelteMap } from "svelte/reactivity";
  import { Tween } from "svelte/motion";
  import { Plus } from "@lucide/svelte";
  import { MAX_ITEMS, edges, edgeAngle, edgeWeights, wedgePath, slotSpans, centerAt, posAt, weightOf, dragSlot, fitLabel, isSubmenu, hasChildren } from "../lib/menu.js";
  import { actionMeta } from "../lib/link.svelte.js";

  // `back` is the angle (degrees) of the slot facing the parent when this is a submenu (null at the root); that slot is
  // drawn as the parent's ghost and clicking it goes up. `onopen(i)` descends into a submenu slice, `onup()` goes back.
  let { items, selected = -1, back = null, parentLabel = "", onselect, onmove, onadd, onremove, onenter, onopen, onup, onresize, onequal } = $props();

  const R_IN = 60, R_OUT = 160, HUB = 34, HALF = 200, LIFT = 6; // viewBox spans ±HALF
  const weights = $derived(items.map(weightOf));
  const rot = $derived(back == null ? 0 : (back * Math.PI) / 180);
  // Where each slice sits (radians, unwrapped) and how wide it is; a fractional slot glides between the centres.
  const lay = $derived(slotSpans(weights, back, false).map(({ center, span }) => ({ center: (center * Math.PI) / 180, span: (span * Math.PI) / 180 })));
  const opts = { duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 200, easing: cubicOut };

  const slots = new SvelteMap(); // item → Tween of its fractional slot (so slices glide into place)
  let drag = $state(null); // { from, slot, pos }: slot = where it would land, pos = its fractional slot under the pointer
  let press = null; // pointer down on a slice, not yet a drag
  let svg = $state();

  const ids = new WeakMap();
  let nextId = 0;
  const idOf = (item) => ids.get(item) ?? (ids.set(item, ++nextId), nextId);

  // While dragging, the other slices shift to make room for the dragged one at its slot.
  const preview = (k, d) => ((j) => (j < d.slot ? j : j + 1))(k < d.from ? k : k - 1);

  $effect(() => {
    const list = items.slice(), d = drag && { ...drag }; // the reads this effect depends on
    untrack(() => {
      for (const k of slots.keys()) if (!list.includes(k)) slots.delete(k);
      list.forEach((item, i) => {
        if (!slots.has(item)) slots.set(item, new Tween(i, opts));
        if (d?.from !== i) slots.get(item).target = d ? preview(i, d) : i;
      });
    });
  });

  const pos = (item, i) => (drag?.from === i ? drag.pos : (slots.get(item)?.current ?? i));

  // ── Pointer: press selects, moving past 6 px starts a drag ──
  function down(e, i) {
    if (e.button) return;
    onselect(i);
    press = { i, x: e.clientX, y: e.clientY };
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  const toView = (e) => {
    const r = svg.getBoundingClientRect(), k = (2 * HALF) / r.width;
    return [(e.clientX - r.left - r.width / 2) * k, (e.clientY - r.top - r.height / 2) * k];
  };
  function move(e) {
    const n = items.length;
    if (!press || n < 2 || (!drag && Math.hypot(e.clientX - press.x, e.clientY - press.y) < 6)) return;
    const [x, y] = toView(e);
    const pos = Math.min(Math.max(posAt(Math.atan2(x, -y), lay), 0), n - 1 + 0.5);
    drag = { from: press.i, slot: dragSlot(x, y, n, HUB, drag?.slot ?? press.i, back, weights), pos };
  }
  function up() {
    const d = drag;
    press = drag = null;
    if (!d) return;
    const t = slots.get(items[d.from]);
    t?.set(d.pos, { duration: 0 }); // start from where the slice was let go, then glide into its slot
    if (t) t.target = d.slot;
    if (d.slot !== d.from) onmove(d.from, d.slot);
  }
  const cancel = () => (press = drag = null);

  // ── Resizing: dragging the border between two slices moves width from one to the other ──
  let edge = $state(null); // [a, b] of the border being dragged
  const grab = (e, ab) => ((edge = ab), e.currentTarget.setPointerCapture(e.pointerId));
  function resize(e) {
    if (!edge) return;
    const [x, y] = toView(e), [a, b] = edge;
    const [wa, wb] = edgeWeights(lay, weights, a, b, Math.atan2(x, -y));
    if (wa !== weights[a]) onresize(a, b, wa, wb);
  }
  const equal = $derived(weights.every((w) => w === 1));

  // ── Keyboard ──
  const focusSlice = async (i) => (await tick(), svg?.querySelector(`[data-i="${i}"]`)?.focus());
  function key(e, i) {
    const n = items.length;
    const dir = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (dir) {
      e.preventDefault();
      if (e.altKey) {
        const to = i + dir;
        if (to >= 0 && to < n) (onmove(i, to), focusSlice(to));
      } else {
        const to = (i + dir + n) % n;
        onselect(to);
        focusSlice(to);
      }
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      onremove(i);
      focusSlice(Math.min(i, n - 2));
    } else if (e.key === "Enter") {
      e.preventDefault();
      onselect(i);
      if (isSubmenu(items[i])) onopen?.(i);
      else onenter?.();
    } else if (e.key === " ") {
      e.preventDefault();
      onselect(i);
    }
  }
</script>

<svelte:window onkeydown={(e) => {
  if (e.defaultPrevented || e.target.closest?.("input, select, textarea")) return;
  if (e.key === "Escape") drag ? cancel() : onup?.();
  else if (e.key === "Backspace" && selected < 0) onup?.();
}} />

<svg bind:this={svg} viewBox="{-HALF} {-HALF} {2 * HALF} {2 * HALF}" role="group" aria-label="Menu wheel">
  {#if !items.length}
    <circle r={R_OUT} class="empty-ring" />
    <text y="-8" class="hint">Add your first slice</text>
    <text y="16" class="sub">An empty menu never opens.</text>
  {/if}
  {#each items as item, i (idOf(item))}
    {@const p = pos(item, i)}
    {@const c = centerAt(p, lay)}
    <g class="slice" class:sel={selected === i} class:dragging={drag?.from === i} data-i={i} role="button" tabindex="0"
       aria-label="Slice {i + 1}: {item.label}{isSubmenu(item) ? ' (submenu)' : ''}" aria-pressed={selected === i}
       style:--dx="{Math.sin(c) * LIFT}px" style:--dy="{-Math.cos(c) * LIFT}px"
       onpointerdown={(e) => down(e, i)} onpointermove={move} onpointerup={up} onpointercancel={cancel}
       ondblclick={() => isSubmenu(item) && onopen?.(i)} onkeydown={(e) => key(e, i)}>
      <title>{item.label || "(no label)"} · {isSubmenu(item) ? `submenu, ${item.items.length} items` : item.action || "no action"}</title>
      <path d={wedgePath(c, lay[i].span, R_IN, R_OUT)} />
      <text x={Math.sin(c) * (R_IN + R_OUT) / 2} y={-Math.cos(c) * (R_IN + R_OUT) / 2}>{fitLabel(item.label ?? "", items.length)}</text>
      {#if isSubmenu(item)}
        <path class="chevron" d="M -3 -4 L 3 0 L -3 4"
              transform="translate({Math.sin(c) * (R_OUT - 14)} {-Math.cos(c) * (R_OUT - 14)}) rotate({(c * 180) / Math.PI - 90})" />
      {/if}
      {#if isSubmenu(item) ? !hasChildren(item) : !actionMeta(item.action)}
        <circle cx={Math.sin(c) * (R_OUT - 30)} cy={-Math.cos(c) * (R_OUT - 30)} r="5" class="warn">
          <title>{isSubmenu(item) ? "Empty submenu: pulling it does nothing" : item.action ? "Unknown action, is its plugin loaded?" : "No action chosen"}</title>
        </circle>
      {/if}
    </g>
  {/each}
  {#each edges(items.length, back) as ab (ab.join())}
    {@const e = edgeAngle(lay, ab[0])}
    <g class="edge" class:active={edge && edge[0] === ab[0] && edge[1] === ab[1]} role="separator" aria-label="Drag to resize slices {ab[0] + 1} and {ab[1] + 1}"
       onpointerdown={(ev) => grab(ev, ab)} onpointermove={resize} onpointerup={() => (edge = null)} onpointercancel={() => (edge = null)}>
      <title>Drag to resize</title>
      <line x1={Math.sin(e) * (R_IN - 6)} y1={-Math.cos(e) * (R_IN - 6)} x2={Math.sin(e) * (R_OUT + 8)} y2={-Math.cos(e) * (R_OUT + 8)} class="hit" />
      <line x1={Math.sin(e) * R_IN} y1={-Math.cos(e) * R_IN} x2={Math.sin(e) * R_OUT} y2={-Math.cos(e) * R_OUT} class="rail" />
      <circle cx={Math.sin(e) * (R_OUT + 10)} cy={-Math.cos(e) * (R_OUT + 10)} r="4" class="grip" />
    </g>
  {/each}
  {#if back != null}
    {@const gx = Math.sin(rot) * (R_IN + R_OUT) / 2}
    {@const gy = -Math.cos(rot) * (R_IN + R_OUT) / 2}
    <line x1="0" y1="0" x2={gx} y2={gy} class="link" />
    <g class="ghost" role="button" tabindex="0" aria-label="Back to {parentLabel || 'the parent menu'}" onclick={() => onup?.()}
       onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onup?.())}>
      <title>Back to {parentLabel || "the parent menu"}</title>
      <circle cx={gx} cy={gy} r="22" />
      <text x={gx} y={gy}>{[...String(parentLabel ?? "")][0] ?? "↩"}</text>
    </g>
  {/if}
  {#if items.length}<circle r={HUB} class="hub" />{/if}
</svg>

<div class="foot">
  <button onclick={onadd} disabled={items.length >= MAX_ITEMS} title={items.length >= MAX_ITEMS ? `A menu holds at most ${MAX_ITEMS} slices` : ""}>
    <Plus size={15} /> Add slice
  </button>
  <span class="muted">{items.length} / {MAX_ITEMS}</span>
  {#if items.length > 1}<button onclick={onequal} disabled={equal} title="Give every slice the same size">Equal sizes</button>{/if}
</div>

<style>
  svg { display: block; width: 100%; max-width: 440px; aspect-ratio: 1; margin: 0 auto; touch-action: none; user-select: none; }
  .slice { cursor: grab; outline: none; transition: transform .15s; animation: appear .2s ease-out; --slice: #0e1229; --hot: #335e9e; }
  .slice path { fill: var(--slice); stroke: var(--line); stroke-width: 1.5; transition: fill .15s, stroke .15s; }
  .slice:hover path { fill: var(--nebula-2); }
  .slice:hover, .slice:focus-visible { transform: translate(var(--dx), var(--dy)); }
  .slice.sel path { fill: var(--hot); stroke: var(--rigel); filter: drop-shadow(0 0 6px #8fc7ff66); }
  .slice:focus-visible path { stroke: var(--rigel); stroke-width: 2.5; }
  .slice.dragging { cursor: grabbing; opacity: .9; transition: none; transform: none; }
  text { fill: var(--star); font: 600 17px var(--display); text-anchor: middle; dominant-baseline: central; pointer-events: none; }
  text.hint { font-size: 15px; }
  text.sub { font: 400 12px var(--ui); fill: var(--dust); }
  .warn { fill: var(--warn); stroke: var(--void); stroke-width: 1.5; }
  .chevron { fill: none; stroke: var(--rigel); stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; pointer-events: none; }
  .link { stroke: var(--line); stroke-width: 2; pointer-events: none; }
  .ghost { cursor: pointer; outline: none; }
  .ghost circle { fill: var(--slice, #0e1229); stroke: var(--line); stroke-width: 1.5; transition: fill .15s, stroke .15s; }
  .ghost:hover circle, .ghost:focus-visible circle { fill: var(--hot, #335e9e); stroke: var(--rigel); filter: drop-shadow(0 0 6px #8fc7ff66); }
  .ghost text { font-size: 14px; }
  .edge { cursor: col-resize; }
  .edge .hit { stroke: transparent; stroke-width: 14; }
  .edge .rail { stroke: var(--rigel); stroke-width: 3; stroke-linecap: round; opacity: 0; transition: opacity .12s; pointer-events: none; }
  .edge .grip { fill: var(--dust); opacity: .45; transition: opacity .12s, fill .12s; pointer-events: none; }
  .edge:hover .rail, .edge.active .rail { opacity: .9; }
  .edge:hover .grip, .edge.active .grip { fill: var(--rigel); opacity: 1; }
  .hub { fill: var(--void); stroke: var(--line); stroke-width: 1.5; pointer-events: none; }
  .empty-ring { fill: none; stroke: var(--line); stroke-width: 1.5; stroke-dasharray: 6 6; }
  .foot { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 12px; }
  @keyframes appear { from { opacity: 0; } }
</style>
