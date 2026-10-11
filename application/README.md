# Application — the Leap control panel

The hub for everything Leap on Arch Linux + Wayland (Hyprland): live device
status, gesture recognition, and a binding system that maps gestures to system
actions (input emulation, Hyprland IPC, D-Bus, shell, app integrations).

Status: **design phase**. GUI toolkit and architecture are being decided; see
the project discussion before adding code here.

Design pillars:
- **Modular** — gestures and actions are plugins; adding one is a single small file.
- **Concise** — short, sectioned, commented code a human can skim.
- **Beautiful** — a modern, fluid interface plus a system tray.
