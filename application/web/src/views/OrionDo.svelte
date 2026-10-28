<script>
  // OrionDo: edit the radial menu (the wheel) and how it behaves. Edits go to the draft, like every other page.
  import Switch from "../components/Switch.svelte";
  import MenuWheel from "../components/MenuWheel.svelte";
  import { orion } from "../lib/link.svelte.js";
  import { addItem, blankItem, moveItem, removeItem, selectionAfterMove, selectionAfterRemove } from "../lib/menu.js";

  const present = $derived(orion.gestures.some((g) => g.name === "oriondo"));
  const conf = () => ((orion.draft.gestures.oriondo ??= {}), orion.draft.gestures.oriondo); // reactive proxy, created on first edit
  const list = () => (conf().items ??= []);
  const items = $derived(orion.draft?.gestures?.oriondo?.items ?? []);
  const enabled = $derived(orion.draft?.gestures?.oriondo?.enabled ?? true);
  const shipped = $derived(orion.gestureDefaults.oriondo?.items);
  let sel = $state(-1);
  $effect(() => { // a discarded draft or a reload can shorten the list under the selection
    if (sel >= items.length) sel = items.length - 1;
  });

  function add() {
    const l = list(), at = sel >= 0 ? sel + 1 : l.length;
    if (addItem(l, [], blankItem(l, []), at)) sel = at;
  }
  function remove(i) {
    removeItem(list(), [], i);
    sel = selectionAfterRemove(sel, i, list().length);
  }
  function move(from, to) {
    moveItem(list(), [], from, to);
    sel = selectionAfterMove(sel, from, to);
  }
  const loadDefaults = () => (conf().items = structuredClone($state.snapshot(shipped)));
</script>

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
      <MenuWheel {items} selected={sel} onselect={(i) => (sel = i)} onmove={move} onadd={add} onremove={remove} />
      {#if !items.length && shipped?.length}
        <p class="load"><button onclick={loadDefaults}>Load the default menu</button></p>
      {/if}
    </section>
    <div class="side">
      <!-- inspector -->
      <!-- settings -->
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
</style>
