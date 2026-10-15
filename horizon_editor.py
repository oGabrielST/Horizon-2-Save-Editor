"""Portable desktop launcher for Horizon 2 Save Editor.

The server exposes only bundled UI assets on loopback. Save files are selected,
processed and exported inside the browser; the server has no save-write API.
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen
import webbrowser

TITLE = "Horizon 2 Save Editor"
VERSION = "0.3.0"
ASSETS = {
    "index.html": "text/html; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
    "studio.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "save-core.js": "text/javascript; charset=utf-8",
    "catalog.js": "text/javascript; charset=utf-8",
    "vendor/sql-wasm-inline.js": "text/javascript; charset=utf-8",
    "vendor/sql.js-LICENSE": "text/plain; charset=utf-8",
    "README.md": "text/plain; charset=utf-8",
    "RESEARCH.md": "text/plain; charset=utf-8",
}


class EditorServer:
    """Serve a fixed in-memory asset map; never expose arbitrary disk paths."""

    def __init__(self, directory: Path):
        assets = {name: ((directory / name).read_bytes(), mime)
                  for name, mime in ASSETS.items()}

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def do_GET(self):
                self.send_asset(body=True)

            def do_HEAD(self):
                self.send_asset(body=False)

            def send_asset(self, body: bool):
                route = unquote(urlsplit(self.path).path)
                name = "index.html" if route == "/" else route.removeprefix("/")
                if name not in assets:
                    self.send_error(404, "Asset not found")
                    return
                data, mime = assets[name]
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if body:
                    try:
                        self.wfile.write(data)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

            def log_message(self, *_args):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.http.server_port}/"
        self.thread = threading.Thread(
            target=self.http.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        self.thread.start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)


class Launcher:
    def __init__(self, root: tk.Tk, server: EditorServer):
        self.root, self.server = root, server
        root.title(TITLE)
        root.geometry("580x480")
        root.minsize(520, 450)
        root.configure(bg="#f3f5f7")
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f7")
        style.configure("TLabel", background="#f3f5f7", foreground="#253040", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 24, "bold"))
        style.configure("Sub.TLabel", foreground="#687386")
        style.configure("TButton", font=("Segoe UI", 11), padding=(16, 12))
        style.configure("Primary.TButton", background="#dc642e", foreground="#ffffff")
        style.map("Primary.TButton", background=[("active", "#bb4d1d")])
        frame = ttk.Frame(root, padding=32)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="HORIZON 2", foreground="#bc5426", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(frame, text=TITLE, style="Title.TLabel").pack(anchor="w", pady=(8, 12))
        ttk.Label(frame, text="Manage your profile, cars and progression.\nEdit a backup and export a new copy.", style="Sub.TLabel").pack(anchor="w")
        ttk.Button(frame, text="Open Save Editor", style="Primary.TButton", command=self.open_editor).pack(fill="x", pady=(24, 10))
        ttk.Button(frame, text="How to use", command=self.show_help).pack(fill="x", pady=(0, 10))
        ttk.Button(frame, text="Exit", command=root.destroy).pack(fill="x")
        self.status = tk.StringVar(value="Ready. Opens in your default browser. Keep this window open while editing.")
        ttk.Label(frame, textvariable=self.status, style="Sub.TLabel", wraplength=490).pack(anchor="w", pady=(20, 8))
        ttk.Label(frame, text=f"v{VERSION}  ·  Local processing  ·  No Python installation required for the EXE", style="Sub.TLabel", wraplength=490).pack(anchor="w")

    def open_editor(self):
        try:
            opened = webbrowser.open(self.server.url, new=2)
        except Exception as error:
            messagebox.showerror(TITLE, f"Could not open your browser.\n\nOpen this address manually:\n{self.server.url}\n\n{error}", parent=self.root)
            return
        self.status.set(f"{'Editor opened.' if opened else 'Open this address in Chrome or Edge:'}\n{self.server.url}\nExport your changes before closing the browser tab.")

    def show_help(self):
        messagebox.showinfo("How to use — " + TITLE,
            "1. Click Open Save Editor.\n"
            "2. Select the complete player-1 backup folder.\n"
            "3. Edit XP, cars, perks or other available fields.\n"
            "4. Click Export edited copy (.zip).\n"
            "5. Close the game and Azimuth. Back up the active save,\n"
            "   then replace it with the exported player-1 folder.\n\n"
            "Active folder: data/titles/1A96545B/saves/player-1\n\n"
            "Car editing, XP and perks are user-tested. Other progression\n"
            "features remain experimental. Direct level editing is disabled.\n\n"
            "Your source backup is never overwritten by this editor.", parent=self.root)


def smoke_test(output: Path) -> int:
    """Check packaged assets, HTTP isolation and native widgets without opening a browser."""
    from urllib.error import HTTPError
    result = {"version": VERSION, "frozen": bool(getattr(sys, "frozen", False))}
    server = root = None
    try:
        server = EditorServer(Path(__file__).resolve().parent)
        root = tk.Tk()
        root.withdraw()
        Launcher(root, server)
        root.update_idletasks()
        for asset in ASSETS:
            with urlopen(server.url + asset, timeout=5) as response:
                assert response.status == 200 and response.read(), asset
        for route in ("../horizon_editor.py", "tests/core.test.cjs", "%2e%2e/README.md"):
            try:
                urlopen(server.url + route, timeout=5)
                raise AssertionError("Unexpected access: " + route)
            except HTTPError as error:
                assert error.code == 404
        with urlopen(server.url, timeout=5) as response:
            html = response.read().decode("utf-8-sig")
            assert '<html lang="en">' in html and 'id="level-input"' not in html
            assert "Horizon 2 Save Editor" in html
        result.update(ok=True, assets=len(ASSETS), native_menu=True, loopback_only=True)
    except Exception as error:
        result.update(ok=False, error=str(error))
    finally:
        if root is not None:
            root.destroy()
        if server is not None:
            server.close()
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--self-test", type=Path, metavar="REPORT_JSON", help="Run packaging checks and exit")
    args = parser.parse_args()
    if args.self_test:
        return smoke_test(args.self_test)
    root = tk.Tk()
    root.withdraw()
    server = None
    try:
        server = EditorServer(Path(__file__).resolve().parent)
        Launcher(root, server)
        root.deiconify()
        root.mainloop()
        return 0
    except Exception as error:
        messagebox.showerror(TITLE, f"Could not start the editor.\n\n{error}\n\nFor the Python version, keep the script and all editor files together.", parent=root)
        return 1
    finally:
        if server is not None:
            server.close()


if __name__ == "__main__":
    raise SystemExit(main())
