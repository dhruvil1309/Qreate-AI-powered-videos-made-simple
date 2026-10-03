"""A small headless-Chrome driver for the UAT runner.

Speaks the DevTools Protocol directly over a WebSocket so the suite needs no
Selenium or Playwright install - only a Chrome or Edge that is already on the
machine. It can navigate, run JavaScript in the page, read the console, and
take screenshots.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket  # from websocket-client

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser() -> str | None:
    for p in CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    return shutil.which("chrome") or shutil.which("chromium") or shutil.which("google-chrome")


class BrowserError(RuntimeError):
    pass


class Browser:
    """One headless browser tab, driven over CDP."""

    def __init__(self, width: int = 1560, height: int = 1000, port: int = 9444,
                 reduced_motion: bool = False) -> None:
        exe = find_browser()
        if not exe:
            raise BrowserError("No Chrome or Edge found; UI cases cannot run.")
        self.width, self.height, self.port = width, height, port
        self.profile = tempfile.mkdtemp(prefix="qreate-uat-")
        args = [
            exe, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions",
            "--disable-background-timer-throttling", "--mute-audio",
            f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
            f"--window-size={width},{height}", "--hide-scrollbars", "about:blank",
        ]
        if reduced_motion:
            args.insert(-1, "--force-prefers-reduced-motion")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._connect()
        self._id = 0
        self.console_errors: list[str] = []
        self._send("Runtime.enable")
        self._send("Log.enable")
        self._send("Page.enable")
        self._send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                   deviceScaleFactor=1, mobile=width < 700,
                   screenWidth=width, screenHeight=height)

    # ---------------------------------------------------------------- plumbing
    def _connect(self) -> None:
        for _ in range(80):
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{self.port}/json/new?about:blank",
                                             method="PUT")
                tid = json.loads(urllib.request.urlopen(req, timeout=2).read())["id"]
                self.ws = websocket.create_connection(
                    f"ws://127.0.0.1:{self.port}/devtools/page/{tid}",
                    timeout=45, suppress_origin=True)
                return
            except Exception:
                time.sleep(0.3)
        self.close()
        raise BrowserError("headless browser never became reachable")

    def _send(self, method: str, **params):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        return self._id

    def _pump(self, want_id: int | None = None, timeout: float = 30):
        """Read messages, recording console output, until `want_id` is answered."""
        end = time.time() + timeout
        self.ws.settimeout(0.5)
        while time.time() < end:
            try:
                msg = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                if want_id is None:
                    return None
                continue
            except Exception:
                return None
            m = msg.get("method")
            if m == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.console_errors.append(
                    (d.get("exception") or {}).get("description") or d.get("text") or "exception")
            elif m == "Log.entryAdded" and msg["params"]["entry"]["level"] == "error":
                e = msg["params"]["entry"]
                self.console_errors.append(f"{e.get('text')} {e.get('url') or ''}".strip())
            elif m == "Runtime.consoleAPICalled" and msg["params"]["type"] == "error":
                args = " ".join(str(a.get("value", a.get("description", "")))
                                for a in msg["params"]["args"])
                self.console_errors.append(args)
            if want_id is not None and msg.get("id") == want_id:
                return msg
        if want_id is not None:
            raise BrowserError(f"timed out waiting for CDP response {want_id}")
        return None

    # ---------------------------------------------------------------- actions
    def goto(self, url: str, settle: float = 2.5) -> None:
        self._send("Page.navigate", url=url)
        self.drain(settle)

    def drain(self, seconds: float) -> None:
        """Let the page run, collecting console output, without blocking on a reply."""
        end = time.time() + seconds
        while time.time() < end:
            self._pump(None, timeout=min(0.5, max(0.05, end - time.time())))

    def js(self, expression: str, timeout: float = 30):
        """Run JavaScript and return its value. Promises are awaited."""
        rid = self._send("Runtime.evaluate", expression=expression,
                         returnByValue=True, awaitPromise=True, userGesture=True)
        msg = self._pump(rid, timeout=timeout)
        result = (msg or {}).get("result", {})
        if "exceptionDetails" in result:
            d = result["exceptionDetails"]
            raise BrowserError((d.get("exception") or {}).get("description") or d.get("text"))
        return result.get("result", {}).get("value")

    def screenshot(self, path: str | Path) -> bool:
        rid = self._send("Page.captureScreenshot", format="png",
                         clip={"x": 0, "y": 0, "width": self.width,
                               "height": self.height, "scale": 1})
        msg = self._pump(rid, timeout=30)
        data = (msg or {}).get("result", {}).get("data")
        if not data:
            return False
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(base64.b64decode(data))
        return True

    def new_errors(self) -> list[str]:
        """Console errors seen so far, then reset. Favicon noise is ignored."""
        self.drain(0.3)
        out = [e for e in self.console_errors if "favicon" not in e.lower()]
        self.console_errors.clear()
        return out

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            self.proc.kill()
        except Exception:
            pass
        shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def have_browser() -> bool:
    return find_browser() is not None and os.name is not None
