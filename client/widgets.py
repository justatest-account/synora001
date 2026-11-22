"""Custom Kivy widgets: icons drawn with canvas instructions (no emoji / image files needed)."""
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle, Triangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ColorProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from textfix import layout_text, shape_line, para_rtl

ACC = (0.43, 0.36, 0.98, 1)
ACC2 = (0.13, 0.82, 0.88, 1)
SURF2 = (0.14, 0.18, 0.32, 1)
TXT = (0.93, 0.95, 1, 1)
AVATAR_COLORS = [(0.43, 0.36, 0.98, 1), (0.13, 0.62, 0.88, 1), (0.9, 0.35, 0.55, 1),
                 (0.95, 0.6, 0.2, 1), (0.2, 0.75, 0.5, 1), (0.7, 0.4, 0.9, 1)]


def avatar_color(name: str):
    return AVATAR_COLORS[sum(ord(c) for c in name) % len(AVATAR_COLORS)]


class GradientBg(Widget):
    top = ColorProperty((0.13, 0.09, 0.36, 1))
    bottom = ColorProperty((0.05, 0.07, 0.14, 1))

    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas:
            Color(1, 1, 1, 1)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd, top=self._tex, bottom=self._tex)
        self._tex()

    def _upd(self, *_):
        self._rect.pos, self._rect.size = self.pos, self.size

    def _tex(self, *_):
        tex = Texture.create(size=(1, 2), colorfmt="rgba")
        buf = bytes(int(max(0, min(1, v)) * 255) for v in list(self.bottom) + list(self.top))
        tex.blit_buffer(buf, colorfmt="rgba", bufferfmt="ubyte")
        tex.mag_filter = "linear"
        self._rect.texture = tex


class PillButton(ButtonBehavior, Label):
    bg = ColorProperty(ACC)


class Icon(ButtonBehavior, Widget):
    kind = StringProperty("back")
    col = ColorProperty(TXT)
    bg = ColorProperty((0, 0, 0, 0))

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self._draw, size=self._draw, kind=self._draw, col=self._draw, bg=self._draw)
        self._draw()

    def _draw(self, *_):
        self.canvas.clear()
        cx, cy = self.center
        d = min(self.width, self.height)
        r = d * 0.30
        lw = dp(1.8)
        k = self.kind
        with self.canvas:
            if self.bg[3] > 0:
                Color(*self.bg)
                Ellipse(pos=(cx - d / 2, cy - d / 2), size=(d, d))
            Color(*self.col)
            if k == "back":
                Line(points=[cx + r * 0.4, cy + r, cx - r * 0.6, cy, cx + r * 0.4, cy - r],
                     width=lw, cap="round", joint="round")
            elif k == "globe":
                Line(circle=(cx, cy, r * 1.15), width=lw)
                Line(ellipse=(cx - r * 0.5, cy - r * 1.15, r, r * 2.3), width=lw * 0.8)
                Line(points=[cx - r * 1.15, cy, cx + r * 1.15, cy], width=lw * 0.8)
            elif k == "dots":
                for dy in (-dp(7), 0, dp(7)):
                    Ellipse(pos=(cx - dp(2.2), cy + dy - dp(2.2)), size=(dp(4.4), dp(4.4)))
            elif k == "send":
                Triangle(points=[cx + r * 1.15, cy, cx - r * 0.9, cy + r * 0.95, cx - r * 0.9, cy - r * 0.95])
            elif k == "plus":
                Line(points=[cx - r * 0.9, cy, cx + r * 0.9, cy], width=lw * 1.2, cap="round")
                Line(points=[cx, cy - r * 0.9, cx, cy + r * 0.9], width=lw * 1.2, cap="round")
            elif k == "lock":
                RoundedRectangle(pos=(cx - r * 0.85, cy - r * 1.0), size=(r * 1.7, r * 1.2), radius=[dp(3)])
                Line(points=[cx - r * 0.5, cy + r * 0.2, cx - r * 0.5, cy + r * 0.8,
                             cx + r * 0.5, cy + r * 0.8, cx + r * 0.5, cy + r * 0.2],
                     width=lw, cap="round", joint="round")


class Ticks(Widget):
    count = NumericProperty(0)          # 0 pending, 1 sent, 2 delivered

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self._draw, size=self._draw, count=self._draw)
        self._draw()

    def _draw(self, *_):
        self.canvas.clear()
        if self.width <= 0:
            return
        x, cy = self.x, self.center_y
        with self.canvas:
            if self.count <= 0:
                Color(1, 1, 1, 0.6)
                Line(circle=(x + dp(5), cy, dp(3.3)), width=dp(1))
                return
            Color(0.6, 1, 0.85, 1) if self.count >= 2 else Color(1, 1, 1, 0.75)
            for i in range(int(min(self.count, 2))):
                o = x + i * dp(4.5)
                Line(points=[o, cy, o + dp(3), cy - dp(3.4), o + dp(8), cy + dp(3.4)],
                     width=dp(1.2), cap="round", joint="round")


class Avatar(Label):
    bg = ColorProperty(ACC)
    online = BooleanProperty(False)


class Field(TextInput):
    pass


class ShapedInput(Field):
    """Input that keeps the LOGICAL text in `raw` and displays the shaped (joined, reordered) version.
    Editing happens at the end of the line (append / backspace), which is what a chat box needs."""
    raw = StringProperty("")
    max_len = NumericProperty(2000)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.multiline = False

    def insert_text(self, substring, from_undo=False):
        substring = substring.replace("\n", " ").replace("\r", "")
        if self.selection_text:
            self.raw = ""
        self.raw = (self.raw + substring)[: int(self.max_len)]
        self._refresh()

    def do_backspace(self, from_undo=False, mode="bkspc"):
        if self.selection_text:
            self.raw = ""
        else:
            self.raw = self.raw[:-1]
        self._refresh()

    def delete_selection(self, from_undo=False):
        self.raw = ""
        self._refresh()

    def clear_text(self):
        self.raw = ""
        self._refresh()

    def _refresh(self):
        shaped = shape_line(self.raw) if self.raw else ""
        rtl = para_rtl(self.raw)
        self.halign = "right" if rtl else "left"
        self.text = shaped
        self.cancel_selection()
        self.cursor = self.get_cursor_from_index(0 if rtl else len(shaped))


_measurers = {}


def _measure_for(font_size):
    key = round(font_size, 1)
    cl = _measurers.get(key)
    if cl is None:
        cl = CoreLabel(font_size=font_size)
        _measurers[key] = cl
    return lambda s: cl.get_extents(s)[0] if s else 0


class MsgLabel(Label):
    """Message text: wrapped on the logical text, then shaped line by line."""
    raw = StringProperty("")
    max_w = NumericProperty(0)
    rtl = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(raw=self._relayout, max_w=self._relayout)
        self._relayout()

    def _relayout(self, *_):
        if not self.raw:
            self.text = ""
            return
        w = max(self.max_w, dp(60))
        text, rtl = layout_text(self.raw, _measure_for(self.font_size), w)
        self.rtl = rtl
        self.text = text


class Bubble(BoxLayout):
    mine = BooleanProperty(False)
    status = NumericProperty(0)
    time_text = StringProperty("")
    raw = StringProperty("")
    max_w = NumericProperty(0)


class ChatItem(ButtonBehavior, BoxLayout):
    title = StringProperty("")
    initial = StringProperty("")
    color = ColorProperty(ACC)
    online = BooleanProperty(False)
    preview = StringProperty("")
    prev_rtl = BooleanProperty(False)
    time_text = StringProperty("")
    unread = NumericProperty(0)
