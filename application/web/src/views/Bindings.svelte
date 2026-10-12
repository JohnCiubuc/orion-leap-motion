<script>
  // Bindings editor: gesture → action (+ arguments), grouped by profile or mode.
  import { Plus, Trash2, Zap } from "@lucide/svelte";
  import Switch from "../components/Switch.svelte";
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

  function add() {
    const b = { gesture: gestureEvents()[0], action: "notify", args: {} };
    if (cur.kind === "mode") b.mode = cur.key;
    else if (cur.key !== "default") b.profile = cur.key;
    orion.draft.bindings.push(b);
  }
  function setAction(b, name) {
    b.action = name;
    b.args = {}; // start from the new action's defaults
  }
  const argValue = (b, k) => b.args?.[k] ?? actionMeta(b.action)?.args[k];
  const setArg = (b, k, v) => ((b.args ??= {}), (b.args[k] = v));
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
    <div class="head muted"><span>Gesture</span><span>Hand</span><span>Action</span><span>Settings</span><span></span></div>
    {#each rows as [b, i] (i)}
      {@const meta = actionMeta(b.action)}
      <div class="row">
        <select bind:value={b.gesture} aria-label="Gesture">
          {#each orion.gestures as g}
            <optgroup label={g.name}>{#each g.events as e}<option value={e}>{e}</option>{/each}</optgroup>
          {/each}
        </select>
        <select value={b.hand ?? ""} onchange={(e) => (b.hand = e.target.value || undefined)} aria-label="Hand">
          <option value="">Either</option><option value="left">Left</option><option value="right">Right</option>
        </select>
        <div>
          <select value={b.action} onchange={(e) => setAction(b, e.target.value)} aria-label="Action">
            {#each orion.actions as a}<option value={a.name}>{a.name}</option>{/each}
          </select>
          {#if meta}<p class="muted doc">{meta.doc}</p>{:else}<p class="bad doc">Unknown action — is its plugin loaded?</p>{/if}
        </div>
        <div class="args">
          {#each Object.keys(meta?.args ?? {}) as k}
            {@const v = argValue(b, k)}
            <label>
              <span>{k}</span>
              {#if meta.choices[k]}
                <select value={v} onchange={(e) => setArg(b, k, e.target.value)}>
                  {#each meta.choices[k] as c}<option>{c}</option>{/each}
                </select>
              {:else if typeof meta.args[k] === "boolean"}
                <Switch checked={v} label={k} onchange={(on) => setArg(b, k, on)} />
              {:else if typeof meta.args[k] === "number"}
                <input type="number" step="any" value={v} onchange={(e) => setArg(b, k, +e.target.value)} />
              {:else}
                <input type="text" value={v} onchange={(e) => setArg(b, k, e.target.value)} />
              {/if}
            </label>
          {:else}<span class="muted">No settings</span>{/each}
        </div>
        <div class="tools">
          <button class="ghost" title="Run this action now" onclick={() => send("test_action", { action: b.action, args: $state.snapshot(b.args ?? {}) })}><Zap size={15} /></button>
          <button class="ghost danger" title="Remove binding" onclick={() => orion.draft.bindings.splice(i, 1)}><Trash2 size={15} /></button>
        </div>
      </div>
    {:else}
      <p class="empty muted">No bindings here yet. Gestures fall back to the default profile.</p>
    {/each}
    <div class="addrow"><button onclick={add}><Plus size={15} /> Add binding</button></div>
  </div>
{/if}

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 18px; flex-wrap: wrap; }
  .tabs { display: flex; gap: 4px; margin-bottom: 12px; flex-wrap: wrap; }
  .tabs button { background: none; border-color: transparent; color: var(--dust); text-transform: capitalize; }
  .tabs button.on { background: var(--nebula-2); border-color: var(--line); color: var(--star); }
  .live { width: 6px; height: 6px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 6px var(--ok); }
  .table { max-width: 1180px; }
  .head, .row { display: grid; grid-template-columns: 190px 92px 230px 1fr 74px; gap: 14px; padding: 10px 16px; align-items: start; }
  .head { font-size: 12px; border-bottom: 1px solid var(--line); }
  .row { border-bottom: 1px solid var(--line); }
  .row select, .row input { width: 100%; }
  .doc { font-size: 12px; margin-top: 4px; line-height: 1.4; }
  .bad { color: var(--bad); }
  .args { display: flex; flex-wrap: wrap; gap: 8px 14px; }
  .args label { display: grid; gap: 3px; font-size: 11.5px; color: var(--dust); min-width: 120px; flex: 1 1 140px; }
  .tools { display: flex; justify-content: flex-end; }
  .tools button { padding: 6px 7px; }
  .empty { padding: 18px 16px; }
  .addrow { padding: 12px 16px; }
</style>
