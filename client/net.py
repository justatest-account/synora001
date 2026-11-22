"""Background WebSocket connection (websocket-client) that never touches the UI thread.

Events are delivered through on_event(kind, data) FROM THE NETWORK THREAD;
the app forwards them to the main thread with Clock.schedule_once.
"""
import json
import ssl
import threading
import urllib.request

import websocket

try:
    import certifi
except Exception:                      # pragma: no cover
    certifi = None


class Net:
    def __init__(self, url, hello, on_event):
        self.url, self.hello, self.on_event = url, hello, on_event
        self.authed = False
        self._stop = threading.Event()
        self._ws = None
        self._backoff = 1
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def send(self, obj) -> bool:
        ws = self._ws
        try:
            if ws is None or ws.sock is None or not ws.sock.connected:
                return False
            ws.send(json.dumps(obj, separators=(",", ":")))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    def _warmup(self):
        """Free hosts put idle servers to sleep: an HTTP GET wakes them before we connect."""
        try:
            u = self.url.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
            ctx = ssl.create_default_context(cafile=certifi.where()) if certifi else None
            urllib.request.urlopen(u, timeout=90, context=ctx).read(64)
        except Exception:
            pass

    def _loop(self):
        self._warmup()
        while not self._stop.is_set():
            self._ws = websocket.WebSocketApp(
                self.url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=lambda ws, e: None,
                on_close=lambda ws, code, msg: None,
            )
            opts = {"ca_certs": certifi.where()} if certifi else {}
            try:
                self._ws.run_forever(ping_interval=20, ping_timeout=10, sslopt=opts)
            except Exception:
                pass
            self._ws = None
            if self._stop.is_set():
                break
            if not self.authed:
                self.on_event("fail", None)
                break
            self.on_event("down", None)
            self._stop.wait(self._backoff)
            self._backoff = min(self._backoff * 2, 20)

    def _on_open(self, ws):
        self._backoff = 1
        ws.send(json.dumps(self.hello, separators=(",", ":")))

    def _on_message(self, ws, message):
        try:
            m = json.loads(message)
        except Exception:
            return
        if isinstance(m, dict):
            self.on_event("msg", m)
