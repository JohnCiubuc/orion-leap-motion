"""Qt host: Waybar tray + a QWebEngineView window around the web UI.

The engine and server run for the app's whole life; the web view exists only
while the panel is open (closing it to the tray frees the browser engine).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

from .config import Config
from .engine import Engine
from .server import Server

ICON = Path(__file__).with_name("assets") / "orion.svg"


def parse_args():
    p = argparse.ArgumentParser(prog="orion-renewal", description="Leap Motion control hub")
    p.add_argument("--demo", action="store_true", help="synthetic hands, no device needed (actions dry-run)")
    p.add_argument("--live-actions", action="store_true", help="with --demo/--replay: really run actions")
    p.add_argument("--replay", metavar="FILE", help="replay a .orec recording")
    p.add_argument("--hidden", action="store_true", help="start in the tray (autostart)")
    p.add_argument("--headless", action="store_true", help="no window/tray; print the UI URL")
    p.add_argument("--dev", action="store_true", help="allow the Vite dev server (localhost:5173)")
    p.add_argument("--port", type=int, help="UI server port")
    return p.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = Config()
    engine = Engine(cfg, demo=args.demo, dry_run=(args.demo or bool(args.replay)) and not args.live_actions)
    server = Server(engine, port=args.port or cfg.general["port"], dev=args.dev)
    server.start()
    engine.start(replay=args.replay)
    print(f"Orion UI: {server.url}" + (f"\n  dev: http://localhost:5173/?port={server.port}&token={server.token}"
                                       if args.dev else ""), flush=True)
    if args.headless:
        signal.sigwait({signal.SIGINT, signal.SIGTERM})
        return
    run_qt(engine, server, hidden=args.hidden)


# ── Qt ────────────────────────────────────────────────────────────────────────

def run_qt(engine: Engine, server: Server, hidden: bool):
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-gpu-rasterization --ignore-gpu-blocklist")
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

    app = QApplication(sys.argv)
    app.setApplicationName("Orion Renewal")
    app.setDesktopFileName("orion-renewal")  # Wayland app_id → Hyprland window rules
    app.setQuitOnLastWindowClosed(False)
    icon = QIcon(str(ICON))
    app.setWindowIcon(icon)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    QTimer(app, timeout=lambda: None, interval=250).start()  # let Python see Ctrl-C

    # ── Panel window (created on demand, destroyed on close) ─────────────────

    class Panel(QMainWindow):
        def __init__(self):
            super().__init__()
            from PySide6.QtWebEngineWidgets import QWebEngineView
            self.setWindowTitle("Orion Renewal")
            self.resize(1360, 860)
            self.view = QWebEngineView(self)
            self.view.page().setBackgroundColor("#07080d")
            self.view.load(QUrl(server.url))
            self.setCentralWidget(self.view)

        def closeEvent(self, ev):
            state["panel"] = None
            self.view.setParent(None)
            self.view.deleteLater()  # tears down the Chromium renderer
            self.deleteLater()
            ev.accept()

    state = {"panel": None}

    def show_panel():
        if state["panel"] is None:
            state["panel"] = Panel()
        p = state["panel"]
        p.show()
        p.raise_()
        p.activateWindow()

    # ── Tray (StatusNotifierItem → Waybar) ───────────────────────────────────

    tray = QSystemTrayIcon(icon, app)
    menu = QMenu()
    menu.addAction("Open Orion", show_panel)
    pause = QAction("Pause gestures", menu, checkable=True)
    pause.toggled.connect(engine.set_paused)
    air = QAction("Air mouse", menu, checkable=True)
    air.toggled.connect(lambda on: engine.set_mode("air_mouse", on))
    menu.addAction(pause)
    menu.addAction(air)
    menu.addAction("Restart controller", lambda: engine.restart_device())
    profile = menu.addAction("")
    profile.setEnabled(False)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: show_panel() if r == QSystemTrayIcon.ActivationReason.Trigger else None)

    def sync_tray():  # reflect changes made from the UI / gestures
        s = engine.status()
        for act, on in ((pause, s["paused"]), (air, "air_mouse" in s["modes"])):
            act.blockSignals(True)
            act.setChecked(on)
            act.blockSignals(False)
        profile.setText(f"Profile: {s['profile']}")
        tray.setToolTip(f"Orion Renewal — {'paused' if s['paused'] else s['profile']}"
                        f"{' · ' + s['device'] if s.get('device') else ' · no device'}")

    QTimer(app, timeout=sync_tray, interval=500).start()
    sync_tray()
    tray.show()
    if not hidden:
        show_panel()
    sys.exit(app.exec())
