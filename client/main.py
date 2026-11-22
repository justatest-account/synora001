"""SYNORA - Where Connections Come Alive.  Kivy client."""
import json
import os
import re
import threading
import time
import uuid

from kivy.config import Config
from kivy.utils import platform

Config.set("input", "mouse", "mouse,multitouch_on_demand")
Config.set("kivy", "exit_on_escape", "0")
if platform in ("win", "linux", "macosx"):
    Config.set("graphics", "width", "420")
    Config.set("graphics", "height", "800")

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import DEFAULT_FONT, LabelBase
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ColorProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.screenmanager import Screen
from kivy.uix.widget import Widget

HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------ fonts
def setup_fonts():
    win = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
    pairs = [
        (os.path.join(HERE, "fonts", "Vazirmatn-Regular.ttf"), os.path.join(HERE, "fonts", "Vazirmatn-Bold.ttf")),
        (os.path.join(win, "segoeui.ttf"), os.path.join(win, "segoeuib.ttf")),
        (os.path.join(win, "tahoma.ttf"), os.path.join(win, "tahomabd.ttf")),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
        ("/system/fonts/NotoNaskhArabic-Regular.ttf", "/system/fonts/NotoNaskhArabic-Bold.ttf"),
        ("/system/fonts/DroidSansArabic.ttf", "/system/fonts/DroidSansArabic.ttf"),
    ]
    for reg, bold in pairs:
        if os.path.exists(reg):
            LabelBase.register(DEFAULT_FONT, fn_regular=reg, fn_bold=bold if os.path.exists(bold) else reg)
            return


setup_fonts()

from crypto_utils import b64d, b64e, decrypt_msg, encrypt_msg, fingerprint, safety_code  # noqa: E402
from i18n import STRINGS, fa_digits  # noqa: E402
from net import Net  # noqa: E402
from textfix import has_rtl, para_rtl, shape  # noqa: E402
from vault import Vault, VaultError  # noqa: E402
from widgets import (Avatar, Bubble, ChatItem, Field, GradientBg, Icon, MsgLabel,  # noqa: E402,F401
                     PillButton, ShapedInput, Ticks, avatar_color)

DEFAULT_SERVER = "ws://127.0.0.1:8765"      # change to wss://YOUR-APP.onrender.com after deploying
USER_RE = re.compile(r"^[a-z0-9_]{3,20}$")
SURF = (0.09, 0.12, 0.22, 1)
SURF2 = (0.14, 0.18, 0.32, 1)
ACC = (0.43, 0.36, 0.98, 1)
MUT = (0.58, 0.63, 0.78, 1)
BG = (0.05, 0.07, 0.14, 1)


def norm_url(u: str) -> str:
    u = u.strip()
    if not u:
        return ""
    if "://" not in u:
        host = u.split("/")[0].split(":")[0]
        local = host in ("localhost", "127.0.0.1") or host.startswith(("192.168.", "10.", "172."))
        u = ("ws://" if local else "wss://") + u
    if u.startswith("https://"):
        u = "wss://" + u[8:]
    elif u.startswith("http://"):
        u = "ws://" + u[7:]
    return u.rstrip("/")


# ------------------------------------------------------------------ screens
def user_filter(s, undo):
    return "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch == "_"))


class AuthScreen(Screen):
    mode = StringProperty("login")

    def user_filter(self, s, undo):
        return user_filter(s, undo)

    def toggle_mode(self):
        self.mode = "register" if self.mode == "login" else "login"
        App.get_running_app().err_key = ""

    def submit(self):
        App.get_running_app().auth(self.mode, self.ids.user_in.text, self.ids.pw_in.text, self.ids.pw2_in.text)


class ChatsScreen(Screen):
    empty = BooleanProperty(True)

    def user_filter(self, s, undo):
        return user_filter(s, undo)

    def start_chat(self):
        name = self.ids.new_user.text.strip().lower()
        if name and App.get_running_app().start_chat(name):
            self.ids.new_user.text = ""


class SettingsScreen(Screen):
    me_text = StringProperty("")
    key_text = StringProperty("")

    def on_pre_enter(self, *a):
        app = App.get_running_app()
        if app.vault:
            self.me_text = "@" + app.me
            self.key_text = fingerprint(app.vault.pub)


class ConvScreen(Screen):
    peer = StringProperty("")
    initial = StringProperty("")
    color = ColorProperty(ACC)
    online = BooleanProperty(False)
    key_changed = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.by_id = {}
        self._bound = False

    # ---- building the message list
    def open(self, peer):
        app = App.get_running_app()
        chat = app.vault.chat(peer)
        self.peer, self.initial, self.color = peer, peer[:1].upper(), avatar_color(peer)
        self.online = peer in app.online_users
        self.key_changed = bool(chat.get("changed"))
        box = self.ids.msgs
        if not self._bound:
            box.bind(width=self._on_width)
            self._bound = True
        box.clear_widgets()
        self.by_id = {}
        box.add_widget(Label(text=app.tr("e2e_note"), size_hint_y=None, height=dp(28),
                             font_size=sp(12), color=MUT))
        for m in chat["msgs"][-150:]:
            self.add_bubble(m, scroll=False)
        self.scroll_bottom()

    def _max_w(self):
        w = self.ids.msgs.width or Window.width
        return max(dp(80), (w - dp(24)) * 0.78 - dp(24))

    def add_bubble(self, m, scroll=True):
        app = App.get_running_app()
        text = app.raw("undecryptable") if m.get("bad") else m["x"]
        b = Bubble(mine=bool(m["me"]), raw=text, max_w=self._max_w(),
                   status=m.get("st", 0), time_text=app.fmt_time(m["ts"], full=True))
        row = BoxLayout(size_hint_y=None, height=b.height)
        b.bind(height=lambda w, h: setattr(row, "height", h))
        if m["me"]:
            row.add_widget(Widget())
            row.add_widget(b)
        else:
            row.add_widget(b)
            row.add_widget(Widget())
        self.ids.msgs.add_widget(row)
        self.by_id[m["i"]] = b
        if scroll:
            self.scroll_bottom()

    def set_status(self, cid, st):
        b = self.by_id.get(cid)
        if b is not None:
            b.status = st

    def _on_width(self, *a):
        Clock.unschedule(self._relayout_all)
        Clock.schedule_once(self._relayout_all, 0.1)

    def _relayout_all(self, *a):
        w = self._max_w()
        for b in self.by_id.values():
            b.max_w = w

    def scroll_bottom(self):
        for d in (0.05, 0.3):
            Clock.schedule_once(lambda dt: setattr(self.ids.scroll, "scroll_y", 0), d)

    # ---- actions
    def send(self):
        inp = self.ids.msg_in
        text = inp.raw.strip()
        if text:
            inp.clear_text()
            App.get_running_app().send_text(self.peer, text)
        Clock.schedule_once(lambda dt: setattr(inp, "focus", True), 0.05)

    def show_safety(self):
        app = App.get_running_app()
        chat = app.vault.chat(self.peer)
        if not chat.get("pk"):
            app.toast(app.tr("err_no_key"))
            return
        g = safety_code(app.vault.pub, b64d(chat["pk"]))
        code = "   ".join(g[:3]) + "\n" + "   ".join(g[3:])

        mv = ModalView(size_hint=(0.92, None), background="", background_color=(0, 0, 0, 0),
                       overlay_color=(0, 0, 0, 0.65), auto_dismiss=True)
        card = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(12), size_hint=(1, None))
        with card.canvas.before:
            Color(*SURF)
            rr = RoundedRectangle(radius=[dp(24)])
        card.bind(pos=lambda w, v: setattr(rr, "pos", v), size=lambda w, v: setattr(rr, "size", v))
        card.bind(minimum_height=card.setter("height"))
        card.bind(height=mv.setter("height"))

        def lab(text, **kw):
            l = Label(text=text, size_hint_y=None, **kw)
            l.bind(texture_size=lambda w, s: setattr(w, "height", s[1] + dp(6)))
            return l

        card.add_widget(lab(app.tr("safety_title"), bold=True, font_size=sp(20)))
        card.add_widget(lab(code, bold=True, font_size=sp(22), color=(0.13, 0.82, 0.88, 1), halign="center"))
        card.add_widget(lab(app.trf("safety_body", peer=self.peer), font_size=sp(13), color=MUT, halign="center"))

        def verified(*a):
            chat["changed"] = False
            self.key_changed = False
            app.mark_dirty()
            mv.dismiss()

        card.add_widget(PillButton(text=app.tr("verified"), bg=ACC, on_release=verified))
        card.add_widget(PillButton(text=app.tr("close"), bg=SURF2, on_release=lambda *a: mv.dismiss()))
        mv.add_widget(card)
        mv.open()


# ------------------------------------------------------------------ app
class SynoraApp(App):
    lang = StringProperty("fa")
    rtl = BooleanProperty(True)
    conn_state = StringProperty("offline")      # offline | connecting | reconnecting | online
    err_key = StringProperty("")
    busy = BooleanProperty(False)
    server_url = StringProperty(DEFAULT_SERVER)
    name_fa = StringProperty("")

    # ---------------- setup
    def build(self):
        self.title = "SYNORA"
        self.vault = None
        self.me = ""
        self.net = None
        self._gen = 0
        self.authed = False
        self.current_peer = None
        self.online_users = set()
        self._waiting = {}            # peer -> incoming messages waiting for the peer's key
        self._want_flush = set()      # peers whose pending outgoing messages wait for a key
        self._new_chat_req = None
        self._dirty = False
        os.makedirs(self.user_data_dir, exist_ok=True)
        self._load_settings()
        self.name_fa = shape("فارسی")
        if platform == "android":
            Window.softinput_mode = "below_target"
        Window.clearcolor = BG
        Window.bind(on_keyboard=self._on_keyboard)
        root = Builder.load_file(os.path.join(HERE, "synora.kv"))
        return root

    def _settings_path(self):
        return os.path.join(self.user_data_dir, "settings.json")

    def _load_settings(self):
        try:
            with open(self._settings_path(), "r", encoding="utf-8") as f:
                s = json.load(f)
            self.lang = s.get("lang", "fa") if s.get("lang") in ("fa", "en") else "fa"
            self.server_url = s.get("server") or DEFAULT_SERVER
        except Exception:
            pass
        self.rtl = self.lang == "fa"

    def _save_settings(self):
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                json.dump({"lang": self.lang, "server": self.server_url}, f)
        except Exception:
            pass

    # ---------------- i18n helpers
    def raw(self, key, **kw):
        s = STRINGS.get(self.lang, STRINGS["en"]).get(key)
        if s is None:
            s = STRINGS["en"].get(key, "")
        return s.format(**kw) if kw else s

    def tr(self, key, _lang=None):
        s = self.raw(key)
        return shape(s) if self.lang == "fa" else s

    def trf(self, key, **kw):
        s = self.raw(key, **kw)
        return shape(s) if self.lang == "fa" else s

    def set_lang(self, lang):
        self.lang = lang
        self.rtl = lang == "fa"
        self._save_settings()
        if self.vault:
            self.refresh_chats()

    def toggle_lang(self):
        self.set_lang("en" if self.lang == "fa" else "fa")

    def fmt_time(self, ts, full=False):
        t, n = time.localtime(ts), time.localtime()
        if (t.tm_year, t.tm_yday) == (n.tm_year, n.tm_yday):
            s = time.strftime("%H:%M", t)
        else:
            s = time.strftime("%m/%d %H:%M" if full else "%m/%d", t)
        return fa_digits(s) if self.lang == "fa" else s

    def toast(self, shaped_text):
        t = self.root.ids.toast
        t.text = shaped_text
        Animation.cancel_all(t)
        (Animation(opacity=1, d=0.15) + Animation(opacity=1, d=2.2) + Animation(opacity=0, d=0.3)).start(t)

    # ---------------- navigation
    def go(self, name, direction="left"):
        sm = self.root.ids.sm
        sm.transition.direction = direction
        sm.current = name

    def back_to_chats(self):
        self.current_peer = None
        if self.vault:
            self.refresh_chats()
        self.go("chats", "right")

    def _on_keyboard(self, window, key, *a):
        if key == 27:
            cur = self.root.ids.sm.current
            if cur == "conv":
                self.back_to_chats()
                return True
            if cur == "settings":
                self.go("chats", "right")
                return True
        return False

    # ---------------- authentication
    def auth(self, mode, user, pw, pw2):
        if self.busy:
            return
        user = user.strip().lower()
        if not USER_RE.match(user):
            self.err_key = "err_bad_username"
            return
        if len(pw) < 8:
            self.err_key = "err_weak_password"
            return
        if mode == "register" and pw != pw2:
            self.err_key = "err_pw_mismatch"
            return
        url = norm_url(self.server_url)
        if not url:
            self.err_key = "err_connect"
            return
        self._save_settings()
        self.err_key = ""
        self.busy = True
        threading.Thread(target=self._auth_worker, args=(mode, user, pw, url), daemon=True).start()

    def _auth_worker(self, mode, user, pw, url):
        """Runs off the UI thread: key derivation (scrypt) is deliberately slow."""
        path = os.path.join(self.user_data_dir, "vault_%s.bin" % user)
        try:
            if mode == "login" and os.path.exists(path):
                vault = Vault.open(path, pw)
            else:
                vault = Vault.new(path, pw, user)
        except VaultError:
            Clock.schedule_once(lambda dt: self._auth_fail("err_vault"), 0)
            return
        Clock.schedule_once(lambda dt: self._auth_connect(mode, user, pw, url, vault), 0)

    def _auth_connect(self, mode, user, pw, url, vault):
        if self.net:
            self.net.stop()
        self.vault, self.me, self.authed = vault, user, False
        hello = {"t": "register" if mode == "register" else "login",
                 "u": user, "p": pw, "pk": b64e(vault.pub)}
        self._gen += 1
        gen = self._gen
        self.conn_state = "connecting"
        self.net = Net(url, hello, lambda k, d: Clock.schedule_once(lambda dt: self._on_net(gen, k, d), 0))
        self.net.start()

    def _auth_fail(self, key):
        self.busy = False
        self.err_key = key
        self.conn_state = "offline"
        self._gen += 1
        if self.net:
            self.net.stop()
            self.net = None
        self.vault = None
        self.authed = False

    def logout(self):
        self._gen += 1
        Clock.unschedule(self._poll)
        if self.net:
            self.net.stop()
            self.net = None
        if self.vault:
            self.vault.save()
        self.vault, self.authed, self.current_peer = None, False, None
        self.online_users, self._waiting, self._want_flush = set(), {}, set()
        self.conn_state, self.busy, self.err_key = "offline", False, ""
        auth = self.root.ids.sm.get_screen("auth")
        auth.ids.pw_in.text = auth.ids.pw2_in.text = ""
        self.go("auth", "right")

    # ---------------- network events (main thread)
    def _on_net(self, gen, kind, data):
        if gen != self._gen:
            return
        if kind == "msg":
            self._on_server(data)
        elif kind == "down":
            if self.authed:
                self.conn_state = "reconnecting"
        elif kind == "fail":
            if self.busy:
                self._auth_fail("err_connect")
            else:
                self.conn_state = "offline"

    def _on_server(self, m):
        t = m.get("t")
        if t == "ok":
            self._on_ok()
        elif t == "err":
            code = m.get("code", "bad_request")
            if not self.authed:
                self._auth_fail("err_" + code)
            else:
                self._new_chat_req = None
                key = "err_" + code
                self.toast(self.tr(key) if key in STRINGS["en"] else self.tr("err_bad_request"))
        elif not self.authed:
            return
        elif t == "msg":
            self._incoming(m)
        elif t == "sent":
            self._set_status(m.get("cid"), 1)
        elif t == "delivered":
            self._set_status(m.get("cid"), 2)
        elif t == "key":
            self._on_key(m)
        elif t == "presence":
            self._on_presence(m)

    def _on_ok(self):
        first = not self.authed
        self.authed = True
        self.conn_state = "online"
        self.net.authed = True
        self.net.hello = {"t": "login", "u": self.me, "p": self.net.hello["p"], "pk": b64e(self.vault.pub)}
        if first:
            self.vault.save()
            self.busy = False
            self.err_key = ""
            auth = self.root.ids.sm.get_screen("auth")
            auth.ids.pw_in.text = auth.ids.pw2_in.text = ""
            self.refresh_chats()
            self.go("chats", "left")
            Clock.schedule_interval(self._poll, 12)
        # (re)connected: refresh keys + presence, then send everything still pending
        peers = list(self.vault.chats)[:20]
        for p in peers:
            self.net.send({"t": "get_key", "u": p})
        self._poll(0)
        for p, c in self.vault.chats.items():
            if any(x["me"] and x.get("st", 0) == 0 for x in c["msgs"]):
                self._deliver_pending(p)

    def _poll(self, dt):
        if self.authed and self.vault and self.conn_state == "online":
            peers = list(self.vault.chats)[:100]
            if peers:
                self.net.send({"t": "who", "u": peers})

    def _on_presence(self, m):
        q, on = set(m.get("q", [])), set(m.get("on", []))
        self.online_users = (self.online_users - q) | on
        conv = self.root.ids.sm.get_screen("conv")
        if self.current_peer:
            conv.online = self.current_peer in self.online_users
        if self.root.ids.sm.current == "chats":
            self.refresh_chats()

    # ---------------- keys
    def _on_key(self, m):
        peer, pk = m.get("u"), m.get("pk")
        if self._new_chat_req == peer:
            self._new_chat_req = None
            if not pk:
                self.toast(self.tr("err_no_such_user"))
                return
            self.vault.chat(peer)["pk"] = pk
            self.mark_dirty()
            self.open_chat(peer)
            return
        chat = self.vault.chats.get(peer)
        if chat is None or not pk:
            return
        old = chat.get("pk")
        if old and old != pk:
            chat["changed"] = True
            if self.current_peer == peer:
                self.root.ids.sm.get_screen("conv").key_changed = True
        chat["pk"] = pk
        self.mark_dirty()
        for w in self._waiting.pop(peer, []):
            self._incoming(w, final=True)
        if peer in self._want_flush:
            self._want_flush.discard(peer)
            self._deliver_pending(peer)

    # ---------------- chats
    def start_chat(self, name):
        if not USER_RE.match(name):
            self.toast(self.tr("err_bad_username"))
            return False
        if name == self.me:
            self.toast(self.tr("err_self_chat"))
            return False
        if name in self.vault.chats:
            self.open_chat(name)
            return True
        if not self.authed or self.conn_state != "online":
            self.toast(self.tr("err_offline"))
            return False
        self._new_chat_req = name
        self.net.send({"t": "get_key", "u": name})
        return True

    def open_chat(self, peer):
        chat = self.vault.chat(peer)
        chat["unread"] = 0
        self.current_peer = peer
        self.root.ids.sm.get_screen("conv").open(peer)
        if self.authed:
            self.net.send({"t": "get_key", "u": peer})
            self.net.send({"t": "who", "u": [peer]})
        self.mark_dirty()
        self.go("conv", "left")

    def refresh_chats(self):
        scr = self.root.ids.sm.get_screen("chats")
        box = scr.ids.chat_list
        box.clear_widgets()
        chats = self.vault.chats if self.vault else {}

        def last_ts(c):
            return c["msgs"][-1]["ts"] if c["msgs"] else c.get("created", 0)

        for peer, c in sorted(chats.items(), key=lambda kv: last_ts(kv[1]), reverse=True):
            last = c["msgs"][-1] if c["msgs"] else None
            if last is None:
                prev = ""
            elif last.get("bad"):
                prev = self.raw("undecryptable")
            else:
                prev = last["x"].replace("\n", " ")[:80]
            item = ChatItem(title=peer, initial=peer[:1].upper(), color=avatar_color(peer),
                            online=peer in self.online_users, preview=shape(prev),
                            prev_rtl=para_rtl(prev), unread=c.get("unread", 0),
                            time_text=self.fmt_time(last["ts"]) if last else "")
            item.bind(on_release=lambda w, p=peer: self.open_chat(p))
            box.add_widget(item)
        scr.empty = not chats

    # ---------------- sending
    def send_text(self, peer, text):
        text = text[:2000]
        chat = self.vault.chat(peer)
        m = {"i": uuid.uuid4().hex[:16], "me": 1, "x": text, "ts": int(time.time()), "st": 0, "bad": 0}
        chat["msgs"].append(m)
        self.root.ids.sm.get_screen("conv").add_bubble(m)
        self.mark_dirty()
        self._deliver(peer, m)

    def _deliver(self, peer, m):
        if not self.authed or self.conn_state != "online":
            return                                   # stays pending; sent after reconnect
        chat = self.vault.chat(peer)
        pk = chat.get("pk")
        if not pk:
            self._want_flush.add(peer)
            self.net.send({"t": "get_key", "u": peer})
            return
        payload = json.dumps({"i": m["i"], "x": m["x"]}, ensure_ascii=False).encode("utf-8")
        n, c = encrypt_msg(self.vault.priv, b64d(pk), self.me, peer, payload)
        self.net.send({"t": "msg", "to": peer, "cid": m["i"], "n": n, "c": c})

    def _deliver_pending(self, peer):
        for m in list(self.vault.chat(peer)["msgs"]):
            if m["me"] and m.get("st", 0) == 0:
                self._deliver(peer, m)

    def _set_status(self, cid, st):
        if not cid:
            return
        for peer, c in self.vault.chats.items():
            for m in reversed(c["msgs"][-100:]):
                if m["i"] == cid and m["me"]:
                    if st > m.get("st", 0):
                        m["st"] = st
                        self.mark_dirty()
                        if self.current_peer == peer:
                            self.root.ids.sm.get_screen("conv").set_status(cid, st)
                    return

    # ---------------- receiving
    def _incoming(self, m, final=False):
        peer = m.get("from")
        if not isinstance(peer, str) or not isinstance(m.get("id"), int):
            return
        chat = self.vault.chat(peer)
        plain = None
        if chat.get("pk"):
            try:
                plain = decrypt_msg(self.vault.priv, b64d(chat["pk"]), peer, self.me, m["n"], m["c"])
            except Exception:
                plain = None
        if plain is None and not final:
            self._waiting.setdefault(peer, []).append(m)
            self.net.send({"t": "get_key", "u": peer})
            return
        bad, text, cid = 0, "", "x%d" % m["id"]
        if plain is not None:
            try:
                obj = json.loads(plain.decode("utf-8"))
                cid, text = str(obj["i"]), str(obj["x"])[:2000]
            except Exception:
                bad = 1
        else:
            bad = 1
        self.net.send({"t": "ack", "id": m["id"]})
        if any(x["i"] == cid for x in chat["msgs"][-200:]):
            return                                   # duplicate after a reconnect
        msg = {"i": cid, "me": 0, "x": text, "ts": int(m.get("ts") or time.time()), "st": 2, "bad": bad}
        chat["msgs"].append(msg)
        self.mark_dirty()
        sm = self.root.ids.sm
        if self.current_peer == peer and sm.current == "conv":
            sm.get_screen("conv").add_bubble(msg)
        else:
            chat["unread"] = chat.get("unread", 0) + 1
            self.toast(self.trf("new_message", peer=peer))
            if sm.current == "chats":
                self.refresh_chats()

    # ---------------- persistence
    def mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            Clock.schedule_once(self._flush_save, 1.0)

    def _flush_save(self, dt=0):
        self._dirty = False
        if self.vault:
            try:
                self.vault.save()
            except Exception:
                pass

    def on_pause(self):
        self._flush_save()
        return True

    def on_stop(self):
        self._flush_save()
        self._save_settings()
        if self.net:
            self.net.stop()


if __name__ == "__main__":
    SynoraApp().run()
