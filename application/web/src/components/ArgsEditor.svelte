<script>
  // Editor for an action's arguments ({ action, args } objects: bindings and mode hooks).
  import Switch from "./Switch.svelte";
  import { orion, actionMeta } from "../lib/link.svelte.js";

  let { item } = $props();
  const meta = $derived(actionMeta(item.action));
  const value = (k) => item.args?.[k] ?? meta?.args[k];
  const set = (k, v) => ((item.args ??= {}), (item.args[k] = v));
  const uid = Math.random().toString(36).slice(2, 8);
</script>

<div class="args">
  {#each Object.keys(meta?.args ?? {}) as k}
    {@const v = value(k)}
    <label>
      <span>{k}</span>
      {#if meta.choices[k]}
        <select value={v} onchange={(e) => set(k, e.target.value)}>
          {#each meta.choices[k] as c}<option>{c}</option>{/each}
        </select>
      {:else if item.action === "orion.mode" && k === "mode"}<!-- modes defined in the config; keeps an unknown current value selectable -->
        <select value={v} onchange={(e) => set(k, e.target.value)}>
          {#each new Set([v, ...Object.keys(orion.draft?.modes ?? {})]) as m}<option>{m}</option>{/each}
        </select>
      {:else if typeof meta.args[k] === "boolean"}
        <Switch checked={v} label={k} onchange={(on) => set(k, on)} />
      {:else if typeof meta.args[k] === "number"}
        <input type="number" step="any" value={v} onchange={(e) => set(k, +e.target.value)} />
      {:else if k === "shortcut"}<!-- global shortcuts registered on this system, as suggestions -->
        <input type="text" value={v} list="gs-{uid}" onchange={(e) => set(k, e.target.value)} />
        <datalist id="gs-{uid}">
          {#each orion.globalShortcuts as g}<option value={g.name}>{g.description}</option>{/each}
        </datalist>
      {:else}
        <input type="text" value={v} onchange={(e) => set(k, e.target.value)} />
      {/if}
    </label>
  {:else}<span class="muted">No settings</span>{/each}
</div>

<style>
  .args { display: flex; flex-wrap: wrap; gap: 8px 14px; }
  label { display: grid; gap: 3px; font-size: 11.5px; color: var(--dust); min-width: 120px; flex: 1 1 140px; }
  input, select { width: 100%; }
</style>
