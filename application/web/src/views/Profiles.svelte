<script>
  // App profiles (matched against the focused window's class) and binding modes.
  import { Plus, Trash2 } from "@lucide/svelte";
  import Switch from "../components/Switch.svelte";
  import { orion, send } from "../lib/link.svelte.js";

  let newProfile = $state(""), newMode = $state("");
  const win = $derived(orion.status.window || "");
  const matches = (rx) => { try { return !!win && new RegExp(rx.replace("(?i)", ""), rx.includes("(?i)") ? "i" : "").test(win); } catch { return false; } };
  const count = (k, v) => orion.draft.bindings.filter((b) => b[k] === v).length;
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  function rename(kind, from, to) {
    to = to.trim().toLowerCase().replace(/\s+/g, "_");
    if (!to || to === from || orion.draft[kind][to]) return;
    orion.draft[kind] = Object.fromEntries(Object.entries(orion.draft[kind]).map(([k, v]) => [k === from ? to : k, v]));
    const key = kind === "profiles" ? "profile" : "mode";
    orion.draft.bindings.forEach((b) => b[key] === from && (b[key] = to));
  }
  function remove(kind, name) {
    delete orion.draft[kind][name];
    const key = kind === "profiles" ? "profile" : "mode";
    orion.draft.bindings = orion.draft.bindings.filter((b) => b[key] !== name);
  }
  function addProfile() {
    const n = newProfile.trim().toLowerCase().replace(/\s+/g, "_");
    if (n && !orion.draft.profiles[n]) orion.draft.profiles[n] = { match: win ? `^${esc(win)}$` : "" };
    newProfile = "";
  }
  function addMode() {
    const n = newMode.trim().toLowerCase().replace(/\s+/g, "_");
    if (n && !orion.draft.modes[n]) orion.draft.modes[n] = { exclusive: false };
    newMode = "";
  }
</script>

<header>
  <h1>Profiles</h1>
  <p class="muted">Last focused app: {#if win}<code>{win}</code>, using <b>{orion.status.profile}</b>{:else}unknown (Hyprland not detected){/if}</p>
</header>

{#if orion.draft}
  <section>
    <h2>App profiles</h2>
    <p class="muted lead">A profile turns on when the focused window's class matches its pattern (a regular expression). The first match wins.</p>
    <div class="panel list">
      {#each Object.entries(orion.draft.profiles) as [name, p] (name)}
        <div class="row">
          <input type="text" value={name} aria-label="Profile name" onchange={(e) => rename("profiles", name, e.target.value)} />
          <label class="grow"><span class="muted">Window class pattern</span><input type="text" class="id" bind:value={p.match} /></label>
          <span class="state" class:on={matches(p.match)}>{matches(p.match) ? "Matches focused app" : "Not matching"}</span>
          <span class="muted n">{count("profile", name)} bindings</span>
          <button class="ghost danger" title="Delete profile and its bindings" onclick={() => remove("profiles", name)}><Trash2 size={15} /></button>
        </div>
      {/each}
      <form class="row add" onsubmit={(e) => (e.preventDefault(), addProfile())}>
        <input type="text" placeholder="New profile, e.g. obs" bind:value={newProfile} />
        <span class="muted grow">{win ? `Starts matching ${win}` : ""}</span>
        <button type="submit" disabled={!newProfile.trim()}><Plus size={15} /> Add profile</button>
      </form>
    </div>
  </section>

  <section>
    <h2>Modes</h2>
    <p class="muted lead">Groups of bindings you switch on and off from the tray or with a gesture. Exclusive modes silence every other binding while on.</p>
    <div class="panel list">
      {#each Object.entries(orion.draft.modes) as [name, m] (name)}
        <div class="row">
          <input type="text" value={name} aria-label="Mode name" onchange={(e) => rename("modes", name, e.target.value)} />
          <label class="inline grow"><Switch bind:checked={m.exclusive} label="Exclusive" /> Exclusive</label>
          <label class="inline"><Switch checked={orion.status.modes?.includes(name)} label="On now" onchange={(on) => send("mode", { mode: name, on })} /> On now</label>
          <span class="muted n">{count("mode", name)} bindings</span>
          <button class="ghost danger" title="Delete mode and its bindings" onclick={() => remove("modes", name)}><Trash2 size={15} /></button>
        </div>
      {/each}
      <form class="row add" onsubmit={(e) => (e.preventDefault(), addMode())}>
        <input type="text" placeholder="New mode, e.g. presenter" bind:value={newMode} />
        <span class="grow"></span>
        <button type="submit" disabled={!newMode.trim()}><Plus size={15} /> Add mode</button>
      </form>
    </div>
  </section>
{/if}

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 22px; flex-wrap: wrap; }
  section { max-width: 980px; margin-bottom: 28px; }
  .lead { margin: 4px 0 12px; max-width: 70ch; }
  .list { overflow: hidden; }
  .row { display: flex; align-items: center; gap: 14px; padding: 12px 16px; border-bottom: 1px solid var(--line); }
  .row:last-child { border-bottom: 0; }
  .row > input:first-child { width: 170px; font-weight: 600; }
  .grow { flex: 1; }
  label.grow { display: grid; gap: 3px; font-size: 11.5px; }
  .inline { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .state { font-size: 12px; color: var(--dust); width: 140px; }
  .state.on { color: var(--ok); }
  .n { font-size: 12px; width: 82px; text-align: right; }
  .add { background: var(--void); }
</style>
