<script>
  // The OrionDo wheel: draws the menu like the on-screen pie and lets you select, reorder (drag or Alt+arrows),
  // add and remove slices. It holds no menu data; the page owns it and passes callbacks.
  import { tick, untrack } from "svelte";
  import { cubicOut } from "svelte/easing";
  import { SvelteMap } from "svelte/reactivity";
  import { Tween } from "svelte/motion";
  import { Plus } from "@lucide/svelte";
  import { MAX_ITEMS, arcPath, sliceCenter, dragSlot, fitLabel } from "../lib/menu.js";
  import { actionMeta } from "../lib/link.svelte.js";

  let { items, selected = -1, onselect, onmove, onadd, onremove, onenter } = $props();

  const R_IN = 60, R_OUT = 160, HUB = 34, HALF = 200, LIFT = 6; // viewBox spans ±HALF
  const TAU = 2 * Math.PI;
  const opts = { duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 200, easing: cubicOut };

  const count = new Tween(Math.max(items.length, 1), opts); // slice count, fractional while the wheel re-lays out (starts settled: no intro)
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
    count.target = Math.max(items.length, 1);
  });
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
  function move(e) {
    const n = items.length;
    if (!press || n < 2 || (!drag && Math.hypot(e.clientX - press.x, e.clientY - press.y) < 6)) return;
    const r = svg.getBoundingClientRect(), k = (2 * HALF) / r.width;
    const x = (e.clientX - r.left - r.width / 2) * k, y = (e.clientY - r.top - r.height / 2) * k;
    const angle = (Math.atan2(x, -y) + TAU) % TAU;
    drag = { from: press.i, slot: dragSlot(x, y, n, HUB, drag?.slot ?? press.i), pos: angle / (TAU / n) };
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
      onenter?.();
    } else if (e.key === " ") {
      e.preventDefault();
      onselect(i);
    }
  }
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && drag && cancel()} />

<svg bind:this={svg} viewBox="{-HALF} {-HALF} {2 * HALF} {2 * HALF}" role="group" aria-label="Menu wheel">
  {#if !items.length}
    <circle r={R_OUT} class="empty-ring" />
    <text y="-8" class="hint">Add your first slice</text>
    <text y="16" class="sub">An empty menu never opens.</text>
  {/if}
  {#each items as item, i (idOf(item))}
    {@const p = pos(item, i)}
    {@const c = sliceCenter(p, count.current)}
    <g class="slice" class:sel={selected === i} class:dragging={drag?.from === i} data-i={i} role="button" tabindex="0"
       aria-label="Slice {i + 1}: {item.label}" aria-pressed={selected === i}
       style:--dx="{Math.sin(c) * LIFT}px" style:--dy="{-Math.cos(c) * LIFT}px"
       onpointerdown={(e) => down(e, i)} onpointermove={move} onpointerup={up} onpointercancel={cancel}
       onkeydown={(e) => key(e, i)}>
      <title>{item.label || "(no label)"} · {item.action || "no action"}</title>
      <path d={arcPath(p, count.current, R_IN, R_OUT)} />
      <text x={Math.sin(c) * (R_IN + R_OUT) / 2} y={-Math.cos(c) * (R_IN + R_OUT) / 2}>{fitLabel(item.label ?? "", items.length)}</text>
      {#if !actionMeta(item.action)}
        <circle cx={Math.sin(c) * (R_OUT - 14)} cy={-Math.cos(c) * (R_OUT - 14)} r="5" class="warn">
          <title>{item.action ? "Unknown action, is its plugin loaded?" : "No action chosen"}</title>
        </circle>
      {/if}
    </g>
  {/each}
  {#if items.length}<circle r={HUB} class="hub" />{/if}
</svg>

<div class="foot">
  <button onclick={onadd} disabled={items.length >= MAX_ITEMS} title={items.length >= MAX_ITEMS ? `A menu holds at most ${MAX_ITEMS} slices` : ""}>
    <Plus size={15} /> Add slice
  </button>
  <span class="muted">{items.length} / {MAX_ITEMS}</span>
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
  .hub { fill: var(--void); stroke: var(--line); stroke-width: 1.5; pointer-events: none; }
  .empty-ring { fill: none; stroke: var(--line); stroke-width: 1.5; stroke-dasharray: 6 6; }
  .foot { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 12px; }
  @keyframes appear { from { opacity: 0; } }
</style>
