
# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


---

# Project notes: OrionDo (resume here)

Last updated 2026-10-28. OrionDo is merged to `master` and pushed (head `4d615d8`). Submenus + skins are on branch `oriondo-submenus` (not merged; needs the user's look on the real overlay). The webcam source is merged to `master` and pushed but is experimental (see Pending 7: not reliable yet). Webcam spec/plan are in `docs/superpowers/`.

## What it is
**OrionDo** = a Kando-style radial menu for the Orion Leap Motion app, driven by the **index fingertip** (not the OS cursor). Peace sign (held ~0.3 s) opens an animated pie centred on the focused monitor; moving the fingertip past `deadzone` (8 mm) hovers a slice; pulling to `pull` (35 mm) fires it. Firing is by movement only. A fingertip tap at the centre, or losing the hand for 1.5 s, closes it. Default items press `1`–`4` via the `input.keys` action (uinput). Wanted later: submenus, launching apps, macros.

## Where things live
- **Engine** (`application/orion/`): `gestures/oriondo.py` (state machine, event shapes `begin/update/fire/end`, `allow()` re-checked every frame), `engine.py` (`_oriondo`, `_menu_ok`, `_menu_close`, runs the fired item's action via the Executor), `overlay.py` (`menu()` throttles updates to ~60 Hz, `ready`), `menu_anim.py` (pure animation model), `overlay_menu.py` (GTK/cairo pie window, pie-sized unanchored layer-shell surface, namespace `orion-menu`), `overlay_gtk.py` (routes `{"type":"menu"}`), `default.toml` (`[gestures.oriondo]` + `[[gestures.oriondo.items]]`).
- **Web UI** (`application/web/src/`): `views/OrionDo.svelte` (page + settings), `components/MenuWheel.svelte` (SVG wheel: select/drag/keyboard), `components/ItemInspector.svelte`, `lib/menu.js` (pure tree ops + geometry, takes a `path` so submenus fit later), `lib/menu.test.js`. Edits go through the shared `orion.draft` → save bar → `save_config` flow.
- **Submenus and skins** (branch `oriondo-submenus`; spec/plan `docs/superpowers/{specs,plans}/2026-10-28-oriondo-submenus*`): an item with an `items` list is a submenu. Pulling it re-centres the pie on the fingertip (events `enter`/`back`, overlay ops likewise); the slot facing the parent is free (hover `-1`) and drawn as the ghost parent; pulling toward it goes back. Layout rule `slot_angles` (Python `gestures/oriondo.py`, `menu_anim.slice_angles`, JS `lib/menu.js slotAngles`) must stay identical. `menu_anim.py` is the skin-neutral model (levels, springs for travel/ghosts/pulse); `menu_ctl.py` is the overlay window's GTK-free logic; skins live in `orion/menu_skins/` (`@skin("name")`, `MOTION` dict, `draw(cr, view, w, h)`, relative imports only, nothing from `orion`); `skin = "aurora"` in `[gestures.oriondo]`, `[overlay] reduced_motion`. Render skin frames off-screen: `ORION_RENDER_DIR=/some/dir python -m pytest tests/test_menu_skins.py`. Editor: `Breadcrumb.svelte`, the Action/Submenu toggle in `ItemInspector`, `path` in `OrionDo.svelte`; limits 12 items per level, 4 levels (editor only).
- **Config**: items are `{label, action, args}` or `{label, items}` (submenu), list order = clockwise position from the top, equal spacing. User config is `~/.config/orion-renewal/config.toml` (the user's own menu is customised: Anki ratings; backup at `config.toml.bak-oriondo`). `Config` does not merge new defaults into an existing file, so a config without `[gestures.oriondo]` has no menu (the UI offers "Load the default menu").
- **Webcam source** (`application/orion/webcam.py`, tests `tests/test_webcam.py`): `landmarks_to_hand` (pure MediaPipe → `Hand`, Leap axes/mm), `HandTracker` (ids, finger debounce, One-Euro smoothing, 0.08 s dropout hold, separate slow depth filter), `WebcamSource` (capture loop, camera auto-detect from `/sys/class/video4linux`, empty frames while the camera stalls). Config `[webcam]`; Settings has a camera select. Spec/plan: `docs/superpowers/{specs,plans}/2026-10-28-webcam-source*`.
- Specs/plans (read these for intent): `docs/superpowers/specs/2026-10-27-oriondo-design.md`, `…-oriondo-ui-design.md`, `docs/superpowers/plans/2026-10-27-oriondo.md`, `…-oriondo-ui.md`.

## Run / test
- Python: `cd application && python -m pytest tests/test_core.py -q` (≈206 pass). Web: `cd application/web && npm test` (18 pass, Node's built-in runner) and `npm run build` (writes git-ignored `application/orion/web`, which the app serves).
- Launcher `~/.local/bin/orion-renewal` is an editable install of this repo (`/home/inathero/Gits/...` is the same dir as `/fast/Gits/...`). `--demo --headless` prints the UI URL without opening a window.
- Handy verification trick used here: headless Chromium (`chromium --headless --remote-debugging-port=… --force-prefers-reduced-motion`) driven over the DevTools protocol with `node` (built-in `WebSocket`) to send real mouse/key events and read the DOM, against a demo engine with `XDG_CONFIG_HOME` pointing at a temp copy of the config. The scripts were throwaway (not in the repo). Never click the inspector's **Test** button in automation: it runs a real action on the focused window.

## Decisions worth remembering
- Tap detection feeds `FingerMotion` the **index tip only** (dropping the peace pose curls the middle finger and read as a tap).
- A hand returning after >0.15 s out of view **re-anchors** the marker at the centre (otherwise it could fire at once). The menu closes without firing if it stops being allowed (paused, exclusive mode, overlay gone).
- Pie window is pie-sized, not monitor-sized (28 % → ~11 % of a core at 4K).
- Gestures page "Reset all" skips OrionDo (it is not a listed family there).
- Pose `peace` is also bound to right-click in the exclusive mouse modes; OrionDo stays out of exclusive modes.

## Pending (nothing unfinished; all of this is optional follow-up)
Closed by the user 2026-10-28 (not fixed, just dropped): former items 1-3 (real-hand tuning, other gestures co-firing while the pie is open, small UI fixes: drag tween restart / focus after deleting last slice / second pointer).
4. Minor engine: update throttle can drop the last 16 ms before a fire; `_menu_open` touched from two threads unlocked; `OverlayHost.send` is a blocking pipe write (pre-existing pattern); marker dot can cover a slice label; README `layerrule` examples omit the `orion-menu` namespace.
5. Minor UI: a11y (12 tab stops, shortcuts undiscoverable, warning dot not in `aria-label`, CSS animations ignore reduced motion); `fitLabel` cuts by code point; slider nudge off/on dirties the draft; clean state push rebuilds the wheel; unknown action shows "No settings"; trigger missing from the choice list shows a blank select.
8. **Submenus, to check by the user on the real overlay**: the feel and timing of travel (`travel_time` 0.2 s, damping ratio 0.68 in `menu_anim.py`/`aurora.py`), whether the pie edge clips against the 560 px window during travel (the pull ring fades while it travels), and whether a second skin is wanted. Not covered by tests: the actual GTK window (`overlay_menu.py`).
7. **Webcam source: known problems after the first real-hand test (2026-10-28), merged but experimental.** It runs (C922, ~24 fps, MediaPipe 1.2.0 + OpenCV 5.0.0 installed in `.venv`, model cached in `~/.cache/orion-renewal/`) but is not usable day to day yet:
   - Tracking is unreliable and glitches (jitter, flicker, wrong poses). Not yet diagnosed: log real detections (landmarks, labels, straightness, `extended`, ids) with a live camera script before tuning anything.
   - Detection needs the hand fully in profile (palm square to the camera, fingers up). Other angles lose or distort the landmarks.
   - A hand held horizontal (pointing at the camera) is not understood, even right after it was seen upright: the track is lost or the pose reads wrong. Ideas: keep the track and last-known pose through a short unreadable stretch, estimate pose from 3D world landmarks instead of image geometry, or a second camera angle.
   - Other issues the user mentioned but did not list. Ask for them.
   - Fixed already, may need re-checking: Left/Right swapped (labels are now swapped when `mirror`), upright hand laid flat (`tilt = 90`), OrionDo opens with `open_palm` on the webcam (`[webcam] trigger`). Known side effect: thumbs up/down misread under the tilt.
   - Unfixed review minors: greedy two-hand matching; normal sign follows the raw label; stale tracks after a stall; a blocked `cap.read()` or unplugged camera is never recovered; `ensure_model` leaves a `.tmp` on a truncated download and has no hash check; missing OpenCV says "No webcam found"; Settings camera list is empty unless the source is webcam; overlapping source threads on a source switch.
   - Constants to tune on a real hand: `webcam.py` ones marked `shortcut:` (`EXTEND_ON/OFF`, `GRAB_*`, `MIN_CUTOFF/BETA/DEPTH_CUTOFF`, `HOLD`) and OrionDo `deadzone`/`tap_trigger` on a webcam.
6. **Roadmap**: launch-app and macro actions (macros need a step-list args editor in `ArgsEditor`).

## How we have been working
Superpowers flow: brainstorm (classify, one question at a time, sectioned design) → written spec → plan → execute. The user chose **native** (inline) execution both times, with one fresh most-capable reviewer on the whole branch at the end; fixes are TDD (test fails first). Feature work goes on a branch; after review the user says "merge and push" and wants `master` pushed. Commit/push only when asked.
