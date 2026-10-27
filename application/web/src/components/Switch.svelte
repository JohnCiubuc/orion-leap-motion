<script>
  let { checked = $bindable(false), label = "", disabled = false, onchange } = $props();
</script>

<button class="switch" role="switch" aria-checked={checked} aria-label={label} {disabled}
        onclick={() => ((checked = !checked), onchange?.(checked))}><i></i></button>

<style>
  .switch:disabled { opacity: .4; cursor: not-allowed; }
  .switch { width: 34px; height: 20px; padding: 0; border-radius: 99px; background: var(--line); border: 0; position: relative; flex: none; }
  .switch i { position: absolute; top: 3px; left: 3px; width: 14px; height: 14px; border-radius: 50%; background: var(--dust); transition: translate .15s, background .15s; }
  .switch[aria-checked="true"] { background: #8fc7ff55; }
  .switch[aria-checked="true"] i { translate: 14px 0; background: var(--rigel); }
</style>
