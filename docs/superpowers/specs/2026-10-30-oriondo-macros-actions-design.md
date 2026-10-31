# OrionDo macros and launch actions: design

Date 2026-10-30. Status: draft for review.

## Goal

Let a menu slice (or any binding or mode hook) run a **recorded keyboard macro**, **launch an app**, **open a URL/folder/file**, and **type a text snippet**. Recording is done from the web UI: click Record, press keys anywhere, watch the steps appear live, click Stop.

Window actions (`hypr.*`) and media/volume (`media.*`, `audio.*`) already exist as actions and are selectable on a slice today. They need no new code and are out of scope.

## Decisions (from brainstorming)

- Macros capture **keys only** (no mouse, no coordinates).
- Replay uses a **fixed gap** between steps (default 40 ms, per-macro `gap`), not recorded delays.
- Recording happens in the **engine**, reading `/dev/input/event*` through evdev (the user is in the `input` group). It only reads; keys still reach the focused app.
- A macro is stored as one action, `input.macro`, with a plain step list in `config.toml`. No separate macro library.
- The app picker lists installed apps from `.desktop` files; a raw command stays available through the `shell` action.

Out of scope: mouse in macros, recorded delays, running other slices from a macro, screenshot/power/clipboard slices, templates, app icons in the picker.

## Components

### 1. Recorder: `orion/macro_rec.py` (new)

Pure core plus a thin device loop.

- `steps_from_events(events)`: pure. Takes `(keycode, value)` pairs (value 1 press, 0 release, 2 repeat ignored) and returns step strings. Rules: modifiers (ctrl, shift, alt, super; left and right fold to one name) held when a non-modifier key is **pressed** prefix that key in press order, so `ctrl+shift+t` is one step emitted on that key's press. A modifier pressed and released with nothing between is a step on its own (`super`). Releases of keys never seen pressed (e.g. the click that started recording) are ignored. Only `KEY_*` codes below `0x100` count, so mouse buttons are ignored.
- `key_name(code)`: inverse of `uinput.keycode`; every produced name must satisfy `keycode(name) == code` (modifiers fold to the left-hand code). Tested by round trip over all codes.
- `MacroRecorder(on_event)`: opens every `/dev/input/event*` with `EV_KEY` and `KEY_A`, skipping devices named `Orion Renewal*` (our own virtual keyboard, so replays are never re-recorded). A selector thread feeds events through the same step logic and calls `on_event({"op": "step", "step": s, "steps": [...]})`, then `{"op": "stop", "steps": [...], "reason": ...}` on end. Does not grab devices.
- Safety: one recording at a time; auto-stops after 120 s, at 200 steps, or when the last UI client disconnects. It is a keylogger while on, so steps are never written to the log and the UI says "Recording captures everything you type, passwords included".

### 2. Engine and server wiring

- `Engine.macro(on: bool)` starts/stops the recorder; its events go out through the existing `on_engine` callback as `kind="macro"`, which `server.on_engine` already broadcasts as `{"type": "macro", "macro": {...}}`.
- `server.command`: new `cmd == "macro"` with `on`.
- If no clients remain when the websocket handler's `finally` runs, stop the recording.
- Errors (no readable input device) are reported as `{"op": "error", "error": "..."}` and shown in the UI; they never raise into the tracking thread.

### 3. Actions

- `input.macro(steps=[], gap=40)` in `actions/uinput.py`: for each step call `tap_keys(step)` then sleep `gap` ms. Runs on the executor thread, so a long macro delays later actions. Bad step names raise (reported via the existing action-error path) after the earlier steps ran.
- `input.type` is extended to all printable ASCII on a US layout (shifted symbols, newline, tab), replacing its current five-entry map, so it works as a snippet action. The editor shows a multi-line box for its `text` arg.
- `app.launch(app="")` in a new `actions/apps.py`: resolves the desktop id (e.g. `firefox.desktop`) to its file via the XDG data dirs and runs `gio launch <file>` detached (`start_new_session`, output discarded), same pattern as `shell`. Unknown id raises.
- `open(target="")` in the same module: `xdg-open <target>` detached.
- `apps.installed()`: scans `applications/` in the XDG data dirs once and caches `[{id, name}]`, skipping `NoDisplay=true` and `Hidden=true`, sorted by name. Exposed in `Engine.state()` as `apps`.

### 4. Web UI

- `lib/link.svelte.js`: `orion.macro = {recording, steps, error}` updated from `{"type":"macro"}` messages; `orion.apps` from state.
- `components/MacroEditor.svelte` (new), used by `ArgsEditor` when the arg is a list (`Array.isArray(meta.args[k])`), so it works in OrionDo, Bindings and Profiles. Shows steps as an editable list (edit text, delete, move up/down, add), a **Record / Stop** button, the privacy note, and while recording a pulsing indicator with steps appended live. Stop replaces the draft's steps only if at least one step was captured. Stopping is done with the mouse; a keyboard Enter on the focused button would be recorded as a step, which the list lets you delete.
- `ArgsEditor`: `app` arg gets a text input with a `datalist` of installed apps (value = id, label = name), as done for `shortcut`; `text` on `input.type` gets a `textarea`.
- Edits flow through the existing `orion.draft` and save bar. The inspector's **Test** button already runs the action, including a macro.

## Error handling

- No input devices readable: recording does not start, UI shows the message (points at the `input` group).
- Replay with no `/dev/uinput`: existing `status` error path from `uinput.keyboard()`.
- Unknown app id or missing `gio`/`xdg-open`: action error through the executor's `on_error`.

## Testing

Python (`tests/test_core.py` style, TDD, fails first):
- `steps_from_events`: plain keys, chord, three-key chord order, lone modifier, stray release, key repeat ignored, mouse buttons ignored.
- `key_name`/`keycode` round trip.
- `input.macro` with `tap_keys` and `time.sleep` monkeypatched: order, gap, error stops the run.
- `input.type` ASCII map covers all printable characters; US shifted symbols map to `shift+<key>`.
- `app.launch` / `open` with `subprocess.Popen` monkeypatched; `installed()` on a temp `applications` dir (NoDisplay skipped, sorted).

Not unit-tested: the evdev device loop and the Svelte component. Verify by hand: record a chord and plain keys in another app with the UI open, confirm the steps and live display, replay via Test, then via a pulled slice; `npm run build` and the existing `npm test` stay green.

## Known limits

- US keyboard layout assumption for `input.type` (uinput sends keycodes, not characters). `shortcut:` comment in code.
- Macros are keycodes: they replay physical keys, so another layout replays different characters.
- Long macros block the action executor while they run.
