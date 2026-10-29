<script>
  // Edits the selected wheel slice: label, action and its arguments, plus a test run and removal.
  import { Zap, Trash2, FolderOpen } from "@lucide/svelte";
  import ArgsEditor from "./ArgsEditor.svelte";
  import { orion, send, actionMeta } from "../lib/link.svelte.js";
  import { isSubmenu, hasChildren, toSubmenu, toAction } from "../lib/menu.js";

  // `canNest`: another level is allowed here. `onopen`: descend into this item when it is a submenu.
  let { item, onremove, onopen, canNest = true, inputref = $bindable() } = $props();
  const sub = $derived(isSubmenu(item));
  function setType(toSub) {
    if (toSub === sub || (toSub && !canNest)) return;
    if (!toSub && hasChildren(item) && !confirm(`Switching to an action removes this submenu's ${item.items.length} item(s). Continue?`)) return;
    toSub ? toSubmenu(item) : toAction(item);
  }
  const meta = $derived(item && actionMeta(item.action));
  // An action the engine doesn't know (a plugin that isn't loaded) stays selectable, so saving never swaps it for another.
  const known = $derived(orion.actions.map((a) => a.name));
  const names = $derived(!item || known.includes(item.action) ? known : [item.action ?? "", ...known]);
  const setAction = (name) => ((item.action = name), (item.args = {})); // start from the new action's defaults
</script>

{#if item}
  <div class="inspector">
    <label>
      <span>Label</span>
      <input type="text" bind:this={inputref} bind:value={item.label} placeholder="Shown on the slice" />
    </label>
    <div class="type" role="group" aria-label="Slice type">
      <button class:on={!sub} aria-pressed={!sub} onclick={() => setType(false)}>Action</button>
      <button class:on={sub} aria-pressed={sub} onclick={() => setType(true)} disabled={!sub && !canNest}
              title={!sub && !canNest ? "Menus nest at most 4 levels deep" : ""}>Submenu</button>
    </div>
    {#if sub}
      <p class="muted doc">Pulling this slice opens a menu of its own. Pull toward the parent to come back.</p>
      <div class="tools">
        <button onclick={onopen}><FolderOpen size={14} /> Open · {item.items.length} item{item.items.length === 1 ? "" : "s"}</button>
        <button class="danger" onclick={onremove}><Trash2 size={14} /> Remove slice</button>
      </div>
      {#if !item.items.length}<p class="bad doc">Empty: add items inside it, or pulling it does nothing.</p>{/if}
    {:else}
      <label>
        <span>Action</span>
        <select value={item.action ?? ""} onchange={(e) => setAction(e.target.value)}>
          {#each names as a}<option value={a}>{a || "Choose an action…"}</option>{/each}
        </select>
      </label>
      {#if meta}<p class="muted doc">{meta.doc}</p>
      {:else}<p class="bad doc">{item.action ? "Unknown action — is its plugin loaded?" : "Choose an action for this slice."}</p>{/if}
      <ArgsEditor {item} />
      <div class="tools">
        <button onclick={() => send("test_action", { action: item.action, args: $state.snapshot(item.args ?? {}) })} disabled={!meta}>
          <Zap size={14} /> Test
        </button>
        <button class="danger" onclick={onremove}><Trash2 size={14} /> Remove slice</button>
      </div>
    {/if}
  </div>
{:else}
  <p class="muted">Select a slice to edit it.</p>
{/if}

<style>
  .inspector { display: grid; gap: 12px; }
  label { display: grid; gap: 4px; font-size: 12px; color: var(--dust); }
  input, select { width: 100%; font-size: 14px; }
  .doc { font-size: 12px; line-height: 1.4; margin-top: -4px; }
  .bad { color: var(--bad); }
  .type { display: flex; gap: 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
  .type button { flex: 1; border: 0; border-radius: 0; background: transparent; padding: 6px 10px; font-size: 13px; }
  .type button.on { background: var(--hot, #335e9e); color: var(--star); }
  .type button:disabled { opacity: .4; cursor: not-allowed; }
  .tools { display: flex; justify-content: space-between; gap: 8px; padding-top: 4px; }
</style>
