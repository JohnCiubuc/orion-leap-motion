<script>
  // App profiles (matched against the focused window's class) and binding modes.
  import { Plus, Trash2, Zap, AppWindow, Terminal, Keyboard } from "@lucide/svelte";
  import Switch from "../components/Switch.svelte";
  import ArgsEditor from "../components/ArgsEditor.svelte";
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
  // ── Mode hooks: actions run when a mode turns on / off ──
  const HOOKS = [["on_enter", "When turned on"], ["on_exit", "When turned off"]];
  const PRESETS = [
    { label: "Launch app", icon: AppWindow, hook: () => ({ action: "shell", args: { cmd: "" } }) },
    { label: "Hyprland dispatch", icon: Terminal, hook: () => ({ action: "hypr.dispatch", args: { cmd: "" } }) },
    { label: "Global shortcut", icon: Keyboard,
      hook: () => ({ action: "hypr.global", args: { shortcut: orion.globalShortcuts[0]?.name ?? "kando:example-menu" } }) },
    { label: "Other action", icon: Plus, hook: () => ({ action: "notify", args: {} }) },
  ];
  const addHook = (m, key, hook) => { m[key] ??= []; m[key].push(hook); }; // push via the reactive proxy
  // Live exclusivity (from the engine): while an exclusive mode is on, nothing else can be switched on
  const liveExclusive = $derived((orion.status.modes ?? []).find((x) => orion.config?.modes?.[x]?.exclusive));

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
    <p class="muted lead">Groups of bindings you switch on and off from the tray or with a gesture. An exclusive mode silences every other binding and keeps other modes off while it's on. Each mode can launch an app, run a Hyprland dispatch or trigger a global shortcut as it turns on or off.</p>
    <div class="panel list">
      {#each Object.entries(orion.draft.modes) as [name, m] (name)}
        {@const blocked = liveExclusive && liveExclusive !== name}
        <div class="mode">
          <div class="row">
            <input type="text" value={name} aria-label="Mode name" onchange={(e) => rename("modes", name, e.target.value)} />
            <label class="inline grow" title="Only this mode's bindings fire while it's on, and no other mode can be on with it">
              <Switch bind:checked={m.exclusive} label="Exclusive" /> Exclusive</label>
            <label class="inline" title={blocked ? `${liveExclusive.replace(/_/g, " ")} is exclusive and on` : ""}>
              <Switch checked={orion.status.modes?.includes(name)} disabled={blocked} label="On now"
                      onchange={(on) => send("mode", { mode: name, on })} /> On now</label>
            <span class="muted n">{count("mode", name)} bindings</span>
            <button class="ghost danger" title="Delete mode and its bindings" onclick={() => remove("modes", name)}><Trash2 size={15} /></button>
          </div>
          {#if blocked}<p class="muted note">Turn off {liveExclusive.replace(/_/g, " ")} (exclusive) to switch this on.</p>{/if}

          <!-- Follow an app: the mode ends when that app's last window closes -->
          <div class="follow">
            <label class="inline"><Switch checked={m.follow_app != null} label="Turn off when an app closes"
              onchange={(on) => (m.follow_app = on ? (win ? `^${esc(win)}$` : "") : undefined)} /> Turn off when an app closes</label>
            {#if m.follow_app != null}
              <label class="grow"><span class="muted">Window class pattern</span>
                <input type="text" class="id" bind:value={m.follow_app} placeholder="(?i)^krita$" /></label>
              <label class="grace"><span class="muted">Wait for it to open</span>
                <span class="num"><input type="number" min="1" max="300" value={m.follow_grace ?? 15}
                  onchange={(e) => (m.follow_grace = +e.target.value)} /> s</span></label>
              {#if win}<button class="ghost" title="Use the last focused app's window class" onclick={() => (m.follow_app = `^${esc(win)}$`)}>Use {win}</button>{/if}
            {/if}
          </div>

          <div class="hooks">
            {#each HOOKS as [key, label]}
              <div class="hookcol">
                <h3>{label}</h3>
                {#each m[key] ?? [] as h, j}
                  <div class="hook">
                    <select value={h.action} aria-label="Action" onchange={(e) => ((h.action = e.target.value), (h.args = {}))}>
                      {#each orion.actions as a}<option value={a.name}>{a.name}</option>{/each}
                    </select>
                    <ArgsEditor item={h} />
                    <div class="tools">
                      <button class="ghost" title="Run now" onclick={() => send("test_action", { action: h.action, args: $state.snapshot(h.args ?? {}) })}><Zap size={14} /></button>
                      <button class="ghost danger" title="Remove" onclick={() => m[key].splice(j, 1)}><Trash2 size={14} /></button>
                    </div>
                  </div>
                {:else}<p class="muted none">Nothing runs.</p>{/each}
                <div class="presets">
                  {#each PRESETS as pr}<button class="ghost" onclick={() => addHook(m, key, pr.hook())}><pr.icon size={13} /> {pr.label}</button>{/each}
                </div>
              </div>
            {/each}
          </div>
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
  .mode { border-bottom: 1px solid var(--line); }
  .mode .row { border-bottom: 0; }
  .note { padding: 0 16px 8px; font-size: 12.5px; color: var(--warn); }
  .follow { display: flex; align-items: end; gap: 14px; padding: 0 16px 12px; flex-wrap: wrap; }
  .follow label.grow { min-width: 220px; }
  .grace { display: grid; gap: 3px; font-size: 11.5px; }
  .grace .num { display: flex; align-items: center; gap: 6px; color: var(--dust); }
  .grace input { width: 72px; }
  .hooks { display: grid; grid-template-columns: 1fr 1fr; gap: 0 18px; padding: 0 16px 14px; }
  .hookcol { display: grid; gap: 8px; align-content: start; padding: 10px 12px; border-radius: var(--r-sm); background: var(--void); }
  .hookcol h3 { font-size: 12.5px; color: var(--dust); font-weight: 500; }
  .hook { display: grid; grid-template-columns: 1fr auto; gap: 6px 8px; padding: 8px; border-radius: var(--r-sm); background: var(--nebula); }
  .hook select { grid-column: 1; }
  .hook :global(.args) { grid-column: 1 / -1; }
  .hook .tools { grid-column: 2; grid-row: 1; display: flex; }
  .hook .tools button { padding: 4px 6px; }
  .none { font-size: 12.5px; }
  .presets { display: flex; flex-wrap: wrap; gap: 2px; }
  .presets button { font-size: 12px; padding: 3px 8px; }
  @media (max-width: 1000px) { .hooks { grid-template-columns: 1fr; gap: 10px; } }
</style>
