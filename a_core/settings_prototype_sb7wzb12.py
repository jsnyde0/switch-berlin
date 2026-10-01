# PROTOTYPE sb-7wzb.12 — wipe me. LAN-servable dev settings: built Vite assets, LAN host.
from a_core.settings import *  # noqa: F403

DJANGO_VITE["default"]["dev_mode"] = False  # noqa: F405
ALLOWED_HOSTS = ["100.111.85.79", "mac-mini", "mac-mini.tail31457a.ts.net", "192.168.0.225", "Jonatans-Mac-mini.local", "localhost", "127.0.0.1"]
