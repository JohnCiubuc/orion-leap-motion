<script>
  // What's loaded, where it came from, and how to write a new plugin.
  import { FolderOpen, Copy } from "@lucide/svelte";
  import { orion, send } from "../lib/link.svelte.js";

  const groups = $derived.by(() => {
    const by = {};
    for (const g of orion.gestures) (by[g.module] ??= { gestures: [], actions: [] }).gestures.push(g.name);
    for (const a of orion.actions) (by[a.module] ??= { gestures: [], actions: [] }).actions.push(a.name);
    return Object.entries(by).sort(([a], [b]) => a.startsWith("orion_plugin") - b.startsWith("orion_plugin") || a.localeCompare(b));
  });
  const label = (m) => m.startsWith("orion_plugin_") ? `${m.slice(13)}.py` : m.replace(/^orion\./, "");

  const EXAMPLE = `# ~/.config/orion-renewal/plugins/my_plugin.py
from orion.gestures import pose
from orion.actions import action


@pose("rock_on", hold=0.4)
def rock_on(hand, p):
    """Index and pinky up, the rest curled."""
    return hand.extended - {"thumb"} == {"index", "pinky"}


@action("say", text="Rock on")
def say(event, text):
    """Speak a phrase with espeak."""
    import subprocess
    subprocess.Popen(["espeak", text])
`;
</script>

<header>
  <h1>Plugins</h1>
  <p class="muted">Every gesture and action is a plugin. Drop a Python file in your plugins folder and restart Orion.</p>
</header>

<div class="cols">
  <section class="panel">
    <div class="sh"><h2>Loaded</h2><button onclick={() => send("reveal", { what: "plugins" })}><FolderOpen size={15} /> Open plugins folder</button></div>
    {#each orion.plugins.filter((p) => !p.ok) as p}
      <p class="err">{p.file.split("/").pop()} failed to load: {p.error}</p>
    {/each}
    {#each groups as [mod, g]}
      <div class="mod">
        <h3>{label(mod)} {#if mod.startsWith("orion_plugin")}<span class="tag">yours</span>{/if}</h3>
        <div class="chips">
          {#each g.gestures as n}<code class="g">{n}</code>{/each}
          {#each g.actions as n}<code>{n}</code>{/each}
        </div>
      </div>
    {/each}
    <p class="muted legend"><code class="g">gesture</code> <code>action</code></p>
  </section>

  <section class="panel">
    <div class="sh"><h2>Write your own</h2>
      <button class="ghost" onclick={() => navigator.clipboard.writeText(EXAMPLE)}><Copy size={15} /> Copy</button></div>
    <pre>{EXAMPLE}</pre>
    <p class="muted">Decorators: <code>@pose</code>, <code>@motion</code>, <code>@continuous</code> for gestures and <code>@action</code> for actions. Extra keyword arguments become sliders and fields in this app.</p>
  </section>
</div>

<style>
  header { display: flex; align-items: baseline; gap: 16px; margin-bottom: 22px; flex-wrap: wrap; }
  .cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; max-width: 1240px; align-items: start; }
  section { padding: 16px 18px; display: grid; gap: 12px; }
  .sh { display: flex; justify-content: space-between; align-items: center; }
  .mod { display: grid; gap: 6px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  code { padding: 1px 7px; border-radius: 4px; background: var(--void); color: var(--dust); font-size: 11.5px; }
  code.g { color: var(--rigel); }
  .tag { font: 500 11px var(--ui); color: var(--betelgeuse); margin-left: 6px; }
  .legend { font-size: 12px; }
  .err { color: var(--bad); font-size: 13px; }
  pre { margin: 0; padding: 14px; background: var(--void); border-radius: var(--r-sm); font: 12.5px/1.6 var(--id); overflow: auto; color: #c9d3f5; }
  @media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }
</style>
