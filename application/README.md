# Orion Renewal

The control hub for the original Leap Motion Controller on **Arch Linux + Hyprland**.
It recognises hand gestures and maps them to system actions: virtual mouse and keyboard
input, Hyprland dispatchers, MPRIS media control, volume, browser shortcuts, shell commands.
It also shows the device's raw stereo IR feed and live 3D hands.

## Quick start

```bash
./install.sh                 # repo root: tracking service (once)
application/setup.sh         # Orion: venv deps, web UI build, launcher, uinput rule
orion-renewal                # or: orion-renewal --demo   (synthetic hands, actions dry-run)
```

To start Orion with Hyprland, add `exec-once = orion-renewal --hidden` to your config. The tray
icon needs Waybar's `tray` module. Closing the window sends Orion to the tray, and tracking
keeps running.

## How it fits together

```
LeapC service ─▶ sources.py ─▶ Frame (frame.py) ─▶ gestures/* ─▶ GestureEvent ─▶ router.py ─▶ actions/*
                 live / demo / replay                pose · motion · path · continuous    profiles · modes · engage
                                     │
                                     └─▶ server.py ──WebSocket──▶ web/ (Svelte) inside app.py (Qt window + tray)
```

| File | Role |
|---|---|
| `orion/frame.py` | Orion's own hand model (numpy). Converts LeapC data to it and packs it for the UI. |
| `orion/sources.py` | Leap device, demo generator, `.orec` replay and recorder. |
| `orion/gestures/__init__.py` | Gesture plugin API: `@pose`, `@motion`, `@continuous`, `Gesture` base class. |
| `orion/gestures/*.py` | Built-in gestures. Shapes use a $P point-cloud recogniser plus a cornerness score. |
| `orion/actions/__init__.py` | Action plugin API: `@action`, plus the executor (actions never block tracking). |
| `orion/actions/*.py` | uinput, Hyprland IPC, MPRIS (D-Bus), wpctl, browser shortcuts, shell, Orion controls. |
| `orion/router.py` | Picks bindings by focused app (profile), active modes and the engage gate. |
| `orion/engine.py` | Wires everything together, loads plugins, and runs the auto-wake check. |
| `orion/device.py` | Controller recovery: USB reset and tracking-service restart. |
| `orion/overlay.py` | Starts the overlay process and turns gesture events into cards. |
| `orion/overlay_gtk.py` | The overlay itself: a GTK4 layer-shell card (system Python). |
| `orion/server.py` | Local web server and WebSocket (127.0.0.1 only, origin check, per-launch token). |
| `orion/app.py` | Qt host: `QWebEngineView` window and Waybar tray. Closing the window frees the web engine. |
| `web/` | Svelte 5 interface. `npm run build` writes into `orion/web/`. |

`hypr.dispatch` works with both Hyprland config styles. On a Lua config (`configProvider: lua`
in `hyprctl systeminfo`), classic commands like `workspace e+1`, `movetoworkspace 2`,
`togglefloating`, `fullscreen 1`, `killactive`, `togglespecialworkspace NAME` and `exec CMD` are
translated to `hl.dsp.…` automatically. Anything else can be written as Lua directly, for example
`hl.dsp.window.resize({ x = 20, y = 0, relative = true })`.

## Modes

Modes are groups of bindings you switch on and off from the tray, the Profiles page or a gesture
(`orion.mode`). In **Profiles → Modes**, each mode can run actions **When turned on** and **When
turned off**: launch an app (`shell`), run a Hyprland dispatch (`hypr.dispatch`), or trigger a
global shortcut an app registered through the desktop portal (`hypr.global`, e.g.
`kando:example-menu`, the same as `bind = …, global, kando:example-menu`). The shortcut field
suggests what's registered on your system (`hyprctl globalshortcuts`).

**Turn off when an app closes** ties a mode to an app's lifetime. Give a window-class pattern
(e.g. `(?i)^krita$`; the **Use …** button fills in the last focused app) and a grace period.
Orion then waits that long for the app's window to appear, which leaves time for an app launched
by the mode's own "When turned on" action. Once it has appeared, the mode switches off as soon
as the last matching window closes, running its "When turned off" actions. If the app never
appears in time, the mode switches off too.

An **exclusive** mode is the only active mode: turning it on switches the others off, and no
other mode can be turned on until it's off again. While it's on, only its own bindings (and
`orion.*` actions) fire.

```toml
[modes.air_mouse]
exclusive = true
on_enter = [{ action = "hypr.global", args = { shortcut = "kando:example-menu" } }]
on_exit  = [{ action = "hypr.dispatch", args = { cmd = "workspace 1" } }]

[modes.drawing]
on_enter = [{ action = "shell", args = { cmd = "krita" } }]
follow_app = "(?i)^krita$"   # off again when Krita closes
follow_grace = 20            # seconds Krita gets to open
```

## Gesture overlay

On by default: each recognised gesture appears as a small translucent card in the top-right
corner of the monitor that has focus, then fades out. Settings → Gesture overlay controls
opacity, duration, corner and whether unbound gestures show too.

The overlay is a **wlr-layer-shell surface**, not a window. Hyprland doesn't tile it, put it on
a workspace, list it, or give it focus, and clicks pass through it. It runs as a small
separate process (GTK4 + `gtk4-layer-shell`, under the system Python) so it can never stall
or crash Orion. Its layer namespace is `orion-overlay`, so you can style it in
`hyprland.conf`:

```ini
layerrule = blur, orion-overlay
layerrule = ignorezero, orion-overlay
layerrule = animation slide, orion-overlay
```

## When the controller falls asleep

Orion counts the controller as asleep when it's connected but sends no frames. The sidebar
then shows **Restart controller**, which is also in the tray menu, under Settings, and
available as the `orion.restart_device` action. A restart:

1. unpauses the tracking service, which pauses itself when the device's frame rate drops;
2. resets the controller over USB, the same as unplugging and replugging it (no root needed,
   thanks to the `uaccess` udev rule);
3. reconnects Orion.

If that's not enough, **Restart tracking service** restarts the daemon (polkit asks for your
password). **Wake automatically** (`auto_wake`, 10 s by default) runs the restart by itself,
at most once a minute. The udev rule installed by `setup.sh` also turns off USB autosuspend
for the controller, a common cause of the sleep in the first place.

## Gestures

| Family | Built in | Emits |
|---|---|---|
| Pose | `thumbs_up` `thumbs_down` `ok` `fist` `open_palm` `peace` `pinch` `engage` | `begin` once held, `end` on release |
| Motion | `swipe.{left,right,up,down}` `palm_flip.{up,down}` `tap` | `fire` |
| Path | `path.{circle,square,triangle,z}` and any shape you record in the UI | `fire` (value = match score) |
| Pinch & hold | `pinch_joy.{up,down,left,right}` `grab_joy.{…}` (relative ratchet: one event per `step` mm moved, then the current position becomes the new reference point) | `begin`, one `fire` per step (value = new reference point), `end` |
| Continuous | `zoom` (two-hand scale) `rotate` (degrees) `pointer` (Δmm) `pinch_drag` | `begin` / `update` / `end` with a value |

In a mode tab of Bindings (e.g. Air mouse), each binding has **Freeze cursor**. While that
gesture is in progress, the cursor holds still. Turn it on for a pinch-to-scroll binding so
scrolling doesn't drag the cursor along; leave it off for pinch-to-drag so the item follows your
hand. For holds (pinch & hold, poses) the freeze lasts from start to release; for one-shot gestures
(swipes, taps) it lasts 0.35 s. Bindings can be dragged by their grip (or Alt+↑/↓) to reorder,
and hovering the line between two rows reveals **New** and **Duplicate**.

Air mouse steers with whatever `[gestures.pointer] track` names: `palm` (default; steady
while you tap or pinch), `knuckles`, `index`, `middle` or `pinch`. You can change it under
Gestures → Pointer → Tune. Out of the box, pinch-and-lift scrolls one notch per 2 cm, and fist-and-lift changes volume.

## Writing a plugin

Drop a file in `~/.config/orion-renewal/plugins/` and restart Orion:

```python
from orion.gestures import pose
from orion.actions import action

@pose("rock_on", hold=0.4)                 # extra kwargs → tunable sliders: name=(default, min, max)
def rock_on(hand, p):
    return hand.extended - {"thumb"} == {"index", "pinky"}

@action("say", text="Rock on")             # kwargs → fields in the bindings editor
def say(event, text):
    import subprocess; subprocess.Popen(["espeak", text])
```

Then bind `rock_on` to `say` in the UI, or in `config.toml`.

## Config

`~/.config/orion-renewal/config.toml` holds general settings, per-gesture tuning, profiles
(window-class regexes), modes and bindings. Hand edits apply live. Saving from the UI keeps
your comments and layout, except comments inside the bindings list, which is rewritten.
[`orion/default.toml`](orion/default.toml) is the annotated starting point.

## Development

```bash
.venv/bin/python -m pytest application/tests       # gesture + routing tests on synthetic hands
.venv/bin/orion-renewal --demo --headless --dev --port 8765 &
npm --prefix application/web run dev               # open the "dev:" URL it printed (hot reload)
```
