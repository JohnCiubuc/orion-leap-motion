"""Local UI server: static Svelte build + one WebSocket per window.

Binary messages carry live data (skeleton every frame, IR when subscribed),
latest-frame-wins so a slow UI never backs up tracking. Text messages are JSON
state/events (server → UI) and commands (UI → server).
Security: binds 127.0.0.1 only, checks Origin, requires a per-launch token.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import subprocess
import threading
from pathlib import Path

from aiohttp import WSMsgType, web

from .actions import ACTIONS
from .config import CONFIG_DIR, PLUGIN_DIR, RECORDINGS_DIR
from .frame import pack_ir, pack_skeleton
from . import menu_preview
from .gestures import GestureEvent

log = logging.getLogger("orion.server")
WEB_DIR = Path(__file__).with_name("web")
DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


class Client:
    def __init__(self, ws):
        self.ws, self.ir = ws, False
        self.skel = self.img = None  # latest pending binary payloads
        self.texts: list[str] = []
        self.wake = asyncio.Event()

    async def pump(self):
        while not self.ws.closed:
            await self.wake.wait()
            self.wake.clear()
            texts, self.texts = self.texts, []
            skel, img, self.skel, self.img = self.skel, self.img, None, None
            for payload in (*texts, skel, img):
                if payload is None:
                    continue
                if isinstance(payload, str):
                    await self.ws.send_str(payload)
                else:
                    await self.ws.send_bytes(payload)


class Server:
    def __init__(self, engine, port: int = 0, dev: bool = False):
        self.engine, self.port, self.dev = engine, port, dev
        self.token = secrets.token_urlsafe(16) if not dev else "dev"
        self.clients: set[Client] = set()
        self.ready = threading.Event()
        engine.listeners.append(self.on_engine)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    # ── Thread / loop ─────────────────────────────────────────────────────────

    def start(self):
        threading.Thread(target=lambda: asyncio.run(self.main()), name="ui-server", daemon=True).start()
        self.ready.wait(10)

    async def main(self):
        self.loop = asyncio.get_running_loop()
        app = web.Application()
        app.router.add_get("/ws", self.ws_handler)
        app.router.add_get("/skin/{name}", self.skin_preview)
        app.router.add_get("/", lambda r: web.FileResponse(WEB_DIR / "index.html"))
        if WEB_DIR.exists():
            app.router.add_static("/", WEB_DIR)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", self.port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.ready.set()
        while True:  # housekeeping: hand-edited config + 1 Hz status
            await asyncio.sleep(1)
            if self.engine.cfg.changed_on_disk():
                self.engine.reload_config()
            self.engine.watchdog()
            self.broadcast({"type": "status", "status": self.engine.status()})

    # ── Engine → clients (called from any thread) ─────────────────────────────

    def on_engine(self, kind, payload):
        if not self.clients:
            return
        if kind == "frame":
            data = pack_skeleton(payload)
            self.loop.call_soon_threadsafe(self._push, "skel", data)
        elif kind == "image":
            self.loop.call_soon_threadsafe(self._push, "img", pack_ir(payload))
        else:
            self.broadcast({"type": kind, kind: payload})

    def broadcast(self, msg: dict):
        text = json.dumps(msg, default=str)
        self.loop.call_soon_threadsafe(self._push, "text", text)

    def _push(self, slot, data):
        for c in self.clients:
            if slot == "text":
                c.texts.append(data)
            elif slot == "img" and not c.ir:
                continue
            else:
                setattr(c, slot, data)
            c.wake.set()

    # ── WebSocket ─────────────────────────────────────────────────────────────

    async def skin_preview(self, request):
        """PNG of a skin for the OrionDo editor (`?labels=[..]&weights=[..]&hue=&invert=1`)."""
        q = request.query
        if q.get("token") != self.token:
            raise web.HTTPForbidden()
        try:
            labels = [str(x) for x in json.loads(q.get("labels", '["1","2","3","4"]'))][:12] or ["1"]
            weights = [min(max(float(x), 0.1), 4.0) for x in json.loads(q.get("weights", "[]"))][: len(labels)]
            weights += [1.0] * (len(labels) - len(weights))
            hue = float(q["hue"]) % 360 if "hue" in q else None
            options = {str(k): str(v) for k, v in json.loads(q.get("options", "{}")).items()}
        except (ValueError, TypeError, AttributeError):
            raise web.HTTPBadRequest()
        try:
            png = await asyncio.to_thread(menu_preview.png, request.match_info["name"].removesuffix(".png"), labels, weights, hue, q.get("invert") == "1", options)
        except (OSError, subprocess.SubprocessError) as e:  # no system Python with pycairo
            log.warning("skin preview failed: %s", e)
            raise web.HTTPServiceUnavailable()
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "max-age=60"})

    async def ws_handler(self, request):
        origin = request.headers.get("Origin", "")
        allowed = {f"http://127.0.0.1:{self.port}"} | (DEV_ORIGINS if self.dev else set())
        if origin not in allowed or request.query.get("token") != self.token:
            raise web.HTTPForbidden()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8 << 20)
        await ws.prepare(request)
        client = Client(ws)
        self.clients.add(client)
        pump = asyncio.create_task(client.pump())
        client.texts.append(json.dumps({"type": "state", "state": self.engine.state()}, default=str))
        client.wake.set()
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        await asyncio.to_thread(self.command, client, json.loads(msg.data))
                    except Exception as e:
                        log.warning("command failed: %s", e)
                        client.texts.append(json.dumps({"type": "error", "error": {"error": str(e)}}))
                        client.wake.set()
        finally:
            self.clients.discard(client)
            pump.cancel()
            self._sync_ir()
        return ws

    def _sync_ir(self):
        if self.engine.source:
            self.engine.source.ir = any(c.ir for c in self.clients)

    # ── Commands from the UI ──────────────────────────────────────────────────

    def command(self, client: Client, m: dict):
        e, cmd = self.engine, m.get("cmd")
        if cmd == "ir":
            client.ir = bool(m["on"])
            self._sync_ir()
        elif cmd == "save_config":
            e.reload_config(m["config"])
        elif cmd == "mode":
            e.set_mode(m["mode"], m.get("on"))
        elif cmd == "pause":
            e.set_paused(bool(m["on"]))
        elif cmd == "record":
            e.set_recording(bool(m["on"]))
        elif cmd == "replay":
            e.replay(str(RECORDINGS_DIR / m["file"]) if m.get("file") else None)
        elif cmd == "overlay_test":
            if e.overlay:
                e.overlay.show("Swipe left", "hypr.dispatch", "right")
        elif cmd == "restart_device":
            e.restart_device(service=bool(m.get("service")))
        elif cmd == "capture":
            e.capture_path(m["name"])
        elif cmd == "test_action":  # "Test" button in the bindings editor
            act = ACTIONS[m["action"]]
            e.executor.submit(act, GestureEvent("test", "fire", None, None, 0.0), m.get("args", {}))
        elif cmd == "reveal":
            folder = {"plugins": PLUGIN_DIR, "config": CONFIG_DIR, "recordings": RECORDINGS_DIR}[m["what"]]
            folder.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(["xdg-open", str(folder)], start_new_session=True)
        elif cmd == "state":
            e.emit_state()
