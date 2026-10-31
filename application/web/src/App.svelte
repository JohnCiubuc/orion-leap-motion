<script>
  // App shell: navigation rail, global status, unsaved-changes bar, active view.
  import { Activity, Hand, Orbit, Cable, AppWindow, Puzzle, Disc, Settings, Pause, Play, RotateCcw } from "@lucide/svelte";
  import { orion, send, dirty, saveDraft, discardDraft } from "./lib/link.svelte.js";
  import Dashboard from "./views/Dashboard.svelte";
  import Gestures from "./views/Gestures.svelte";
  import OrionDo from "./views/OrionDo.svelte";
  import Bindings from "./views/Bindings.svelte";
  import Profiles from "./views/Profiles.svelte";
  import Plugins from "./views/Plugins.svelte";
  import Recorder from "./views/Recorder.svelte";
  import SettingsView from "./views/Settings.svelte";

  const VIEWS = [
    { id: "live", label: "Live", icon: Activity, view: Dashboard },
    { id: "gestures", label: "Gestures", icon: Hand, view: Gestures },
    { id: "oriondo", label: "OrionDo", icon: Orbit, view: OrionDo },
    { id: "bindings", label: "Bindings", icon: Cable, view: Bindings },
    { id: "profiles", label: "Profiles", icon: AppWindow, view: Profiles },
    { id: "plugins", label: "Plugins", icon: Puzzle, view: Plugins },
    { id: "recorder", label: "Recorder", icon: Disc, view: Recorder },
    { id: "settings", label: "Settings", icon: Settings, view: SettingsView },
  ];
  let current = $state(location.hash.slice(2) || "live");
  const View = $derived(VIEWS.find((v) => v.id === current)?.view ?? Dashboard);
  const go = (id) => ((current = id), history.replaceState(null, "", `${location.search}#/${id}`));
  $effect(() => {
    const sync = () => (current = location.hash.slice(2) || "live");
    addEventListener("hashchange", sync);
    return () => removeEventListener("hashchange", sync);
  });
  const s = $derived(orion.status);
  const asleep = $derived(orion.connected && s.source === "leap" && s.connected && !s.streaming);
  $effect(() => { // notices fade after a few seconds
    if (!orion.notice) return;
    const t = setTimeout(() => (orion.notice = null), 6000);
    return () => clearTimeout(t);
  });
</script>

<div class="shell">
  <!-- ── Navigation rail ── -->
  <nav>
    <div class="brand">
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <g stroke="currentColor" stroke-width="2" opacity=".55">
          <line x1="20" y1="14" x2="27" y2="30" /><line x1="44" y1="16" x2="37" y2="30" />
          <line x1="27" y1="30" x2="37" y2="30" /><line x1="27" y1="30" x2="22" y2="50" />
          <line x1="37" y1="30" x2="44" y2="49" />
        </g>
        <circle cx="20" cy="14" r="3.4" fill="var(--betelgeuse)" /><circle cx="44" cy="16" r="3" fill="var(--star)" />
        <circle cx="27" cy="30" r="2.4" fill="var(--star)" /><circle cx="32" cy="30" r="2.4" fill="var(--star)" />
        <circle cx="37" cy="30" r="2.4" fill="var(--star)" /><circle cx="22" cy="50" r="3" fill="var(--star)" />
        <circle cx="44" cy="49" r="3.6" fill="var(--rigel)" />
      </svg>
      <div><b>Orion</b><span>Renewal</span></div>
    </div>
    {#each VIEWS as v (v.id)}
      <button class="nav" class:on={current === v.id} onclick={() => go(v.id)} aria-current={current === v.id}>
        <v.icon size={17} strokeWidth={1.75} />{v.label}
      </button>
    {/each}

    <div class="foot">
      <div class="device">
        <span class="dot" class:live={s.connected && orion.connected && !asleep} class:asleep></span>
        {#if !orion.connected}Reconnecting to engine…
        {:else if asleep}Controller asleep
        {:else if s.connected}{({ leap: "Leap Motion", leap_mp: "Leap (MediaPipe)" })[s.source] ?? s.source} · {Math.round(orion.fps)} fps{s.agreement ? ` · ${s.agreement}` : ""}{s.delegate ? ` · ${s.delegate.toUpperCase()}` : ""}
        {:else}{s.error || "No device found"}{/if}
      </div>
      {#if s.connected && s.error}<div class="small err">{s.error}</div>{/if}
      {#if asleep || (orion.connected && s.source === "leap" && !s.connected)}
        <button class="wake" onclick={() => send("restart_device")}><RotateCcw size={14} /> Restart controller</button>
      {/if}
      <div class="muted small">Profile <b>{s.profile ?? "default"}</b>{#each s.modes ?? [] as m} · {m.replace("_", " ")}{/each}</div>
      <button class="pause" class:paused={s.paused} onclick={() => send("pause", { on: !s.paused })}>
        {#if s.paused}<Play size={14} /> Resume gestures{:else}<Pause size={14} /> Pause gestures{/if}
      </button>
    </div>
  </nav>

  <!-- ── Active view ── -->
  <main>
    {#if s.dry_run}<div class="banner">Demo mode: gestures are recognised and shown, but actions don't run.</div>{/if}
    {#if orion.notice}<div class="banner" class:ok={orion.notice.ok}>{orion.notice.text}</div>{/if}
    {#each orion.errors.slice(0, 1) as e (e.at)}
      <div class="banner bad">{e.action ? `${e.action} failed: ` : ""}{e.error}
        <button class="ghost" onclick={() => (orion.errors = [])}>Dismiss</button></div>
    {/each}
    <View />
  </main>

  {#if orion.draft && dirty()}
    <div class="savebar panel">
      <span>You have unsaved changes.</span>
      <button class="ghost" onclick={discardDraft}>Discard</button>
      <button class="primary" onclick={saveDraft}>Save changes</button>
    </div>
  {/if}
</div>

<style>
  .shell { display: grid; grid-template-columns: 216px 1fr; height: 100vh; }
  nav { display: flex; flex-direction: column; gap: 2px; padding: 18px 12px; border-right: 1px solid var(--line); background: #0c112a; }
  .brand { display: flex; align-items: center; gap: 10px; padding: 2px 8px 22px; color: var(--star); }
  .brand svg { width: 34px; height: 34px; }
  .brand b { font: 600 17px var(--display); display: block; line-height: 1.1; }
  .brand span { font: 500 12px var(--display); color: var(--dust); }
  .nav { background: none; border: 0; justify-content: flex-start; gap: 11px; padding: 8px 10px; color: var(--dust); font-weight: 500; }
  .nav:hover { color: var(--star); background: var(--nebula); }
  .nav.on { color: var(--star); background: var(--nebula-2); box-shadow: inset 2px 0 0 var(--rigel); }
  .foot { margin-top: auto; display: grid; gap: 8px; padding: 12px 8px 0; border-top: 1px solid var(--line); font-size: 12.5px; }
  .device { display: flex; align-items: center; gap: 8px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--bad); flex: none; }
  .dot.live { background: var(--ok); box-shadow: 0 0 8px var(--ok); }
  .dot.asleep { background: var(--warn); }
  .wake { justify-content: center; border-color: var(--warn); color: var(--warn); }
  .small { font-size: 12px; }
  .pause { justify-content: center; margin-top: 4px; }
  .pause.paused { border-color: var(--warn); color: var(--warn); }
  main { overflow: auto; padding: 26px 30px 90px; position: relative; }
  .banner { margin-bottom: 16px; padding: 9px 14px; border-radius: var(--r-sm); background: #8fc7ff14; border: 1px solid #8fc7ff33; color: var(--rigel); display: flex; align-items: center; justify-content: space-between; }
  .banner.ok { background: #7ee2b814; border-color: #7ee2b840; color: var(--ok); }
  .banner.bad { background: #ff7a8a14; border-color: #ff7a8a40; color: var(--bad); }
  .savebar { position: fixed; bottom: 18px; left: calc(50% + 108px); translate: -50% 0; display: flex; align-items: center; gap: 10px; padding: 8px 8px 8px 16px; box-shadow: 0 10px 40px #000a; }
  .err { color: var(--bad); }
</style>
