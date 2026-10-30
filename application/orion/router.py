"""Gesture → action routing: profiles (per focused app), modes, engage gate, pause."""

from __future__ import annotations

import re

from .actions import ACTIONS
from .gestures import GestureEvent

TRIGGER = ("begin", "fire")  # phases that trigger one-shot actions
POINTERS = ("pointer", "desktop_pointer")  # gestures that move the cursor (held still by freeze_pointer)


class Router:
    def __init__(self, config, submit):
        self.submit = submit  # (Action, event, args) → None
        self.paused, self.modes, self.window = False, set(), ""
        self.armed_until = 0.0
        self.live: set[tuple] = set()  # continuous gestures whose begin was let through
        self.open: set[tuple] = set()  # (gesture, hand) between its begin and end
        self.sessions: set[tuple] = set()  # open holds already engaged: repeats need no new engage
        self.frozen: dict[tuple, float] = {}  # (gesture, hand) → until: air-mouse cursor held still
        self.configure(config)

    def configure(self, cfg):
        self.bindings = cfg["bindings"]
        self.profiles = {k: re.compile(v.get("match", "$^")) for k, v in cfg["profiles"].items()}
        self.exclusive_profiles = {k for k, v in cfg["profiles"].items() if v.get("exclusive")}
        self.mode_cfg = cfg["modes"]
        self.engage_required = cfg.general["engage_required"]
        self.engage_window = cfg.general["engage_window"]
        self.modes &= set(self.mode_cfg)

    # ── Context ───────────────────────────────────────────────────────────────

    @property
    def profile(self) -> str:
        return next((name for name, rx in self.profiles.items() if rx.search(self.window)), "default")

    @property
    def profile_exclusive(self) -> bool:
        """The focused app's profile keeps the default bindings out (like an exclusive mode, but per app)."""
        return self.profile in self.exclusive_profiles

    @property
    def exclusive(self) -> bool:
        return any(self.mode_cfg.get(m, {}).get("exclusive") for m in self.modes)

    @property
    def armed(self) -> bool:
        return self.armed_until > 0

    # ── Freeze cursor: bindings with freeze_pointer hold the air-mouse cursor still ──

    FREEZE_TAP = 0.35  # s, for one-shot gestures (a tap, a swipe) outside a hold

    def _freeze(self, ev: GestureEvent, session: tuple):
        base = session[0]
        if ev.phase == "begin":  # a hold starts: freeze now if any of its bindings asks (e.g. pinch_joy.up)
            fam = lambda g: g == base or g.startswith(base + ".")  # noqa: E731
            if any(b.get("freeze_pointer") for b in self.candidates(ev, fam)):
                self.frozen[session] = float("inf")
        elif ev.phase == "end":
            self.frozen.pop(session, None)
        elif ev.phase == "fire" and any(b.get("freeze_pointer") for b in self.candidates(ev)):
            self.frozen.setdefault(session, ev.t + self.FREEZE_TAP)

    def pointer_frozen(self, t: float) -> bool:
        self.frozen = {k: u for k, u in self.frozen.items() if u > t}
        return bool(self.frozen)

    def candidates(self, ev: GestureEvent, gesture=None) -> list[dict]:
        """Bindings that apply to `ev` right now. `gesture(name) -> bool` widens the name match."""
        same = gesture or (lambda g: g == ev.name)
        match = [b for b in self.bindings if same(b.get("gesture", ""))
                 and b.get("hand") in (None, "", ev.hand) and b.get("action") in ACTIONS]
        moded = [b for b in match if b.get("mode") in self.modes]
        if self.exclusive:
            return moded + [b for b in match if not b.get("mode") and b["action"].startswith("orion.")]
        plain = [b for b in match if not b.get("mode")]
        prof = self.profile
        if prof in self.exclusive_profiles:  # only the profile's own bindings, plus the default orion.* controls
            return moded + [b for b in plain if b.get("profile") == prof] + [
                b for b in plain if b.get("profile", "default") == "default" and b["action"].startswith("orion.")]
        return moded + ([b for b in plain if b.get("profile") == prof]
                        or [b for b in plain if b.get("profile", "default") == "default"])

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(self, ev: GestureEvent) -> list[str]:
        """Dispatch `ev`; returns the names of actions triggered (for the UI feed)."""
        if ev.name == "engage" and ev.phase == "begin":
            self.armed_until = ev.t + self.engage_window
        if self.armed_until and ev.t > self.armed_until:
            self.armed_until = 0.0
        key, fired, consumed = (ev.name, ev.hand), [], False
        session = (ev.name.split(".")[0], ev.hand)
        if ev.phase == "begin":
            self.open.add(session)
        elif ev.phase == "end":
            self.open.discard(session)
            self.sessions.discard(session)
        self._freeze(ev, session)  # before the early return below: an unbound hold's end must still unfreeze
        if ev.phase in ("update", "end") and key not in self.live:
            return fired  # its begin was blocked (paused / not engaged)
        if ev.name in POINTERS and ev.phase == "update" and self.pointer_frozen(ev.t):
            return fired  # cursor frozen by a gesture in progress (e.g. pinch-scrolling)
        for b in self.candidates(ev):
            act = ACTIONS[b["action"]]
            if self.paused and not act.name.startswith("orion."):
                continue
            if not act.continuous and ev.phase not in TRIGGER:
                continue
            gated = (self.engage_required and ev.phase in TRIGGER and not b.get("mode") and ev.name != "engage"
                     and not act.name.startswith("orion.") and session not in self.sessions)
            if gated and not self.armed:
                continue
            consumed |= gated
            self.submit(act, ev, b.get("args", {}))
            fired.append(act.name)
        if consumed:
            self.armed_until = 0.0  # engage arms exactly one gesture (or one joystick hold)
            if session in self.open:  # e.g. a pinch_joy hold: its repeats ride on this engage
                self.sessions.add(session)
        if ev.phase == "begin" and fired:
            self.live.add(key)
        elif ev.phase == "end":
            self.live.discard(key)
        return fired
