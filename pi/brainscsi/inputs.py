"""Replay the SE's keyboard and mouse on the Pi's desktop.

Key events arrive as Mac virtual key codes (the same codes for the SE's ADB
keyboard and the M0110), including the modifier keys themselves, because the
Mac client reads the whole keyboard with GetKeys() and reports every change.

Mapping choices, so the SE feels like a Mac:
  Command -> Ctrl   (Cmd-C copies, Cmd-Q quits)
  Option  -> Alt
  Control -> Super
"""
import shutil
import subprocess

# Mac virtual key code -> X keysym name (US layout)
MAC_TO_X = {
    0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x", 8: "c", 9: "v",
    11: "b", 12: "q", 13: "w", 14: "e", 15: "r", 16: "y", 17: "t",
    18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5", 24: "equal", 25: "9",
    26: "7", 27: "minus", 28: "8", 29: "0", 30: "bracketright", 31: "o", 32: "u",
    33: "bracketleft", 34: "i", 35: "p", 36: "Return", 37: "l", 38: "j",
    39: "apostrophe", 40: "k", 41: "semicolon", 42: "backslash", 43: "comma",
    44: "slash", 45: "n", 46: "m", 47: "period", 48: "Tab", 49: "space",
    50: "grave", 51: "BackSpace", 52: "KP_Enter", 53: "Escape",
    55: "Control_L",   # Command
    56: "Shift_L", 57: "Caps_Lock",
    58: "Alt_L",       # Option
    59: "Super_L",     # Control
    65: "KP_Decimal", 67: "KP_Multiply", 69: "KP_Add", 71: "Clear",
    75: "KP_Divide", 76: "KP_Enter", 78: "KP_Subtract", 81: "KP_Equal",
    82: "KP_0", 83: "KP_1", 84: "KP_2", 85: "KP_3", 86: "KP_4", 87: "KP_5",
    88: "KP_6", 89: "KP_7", 91: "KP_8", 92: "KP_9",
    96: "F5", 97: "F6", 98: "F7", 99: "F3", 100: "F8", 101: "F9", 103: "F11",
    109: "F10", 111: "F12", 114: "Help", 115: "Home", 116: "Prior",
    117: "Delete", 118: "F4", 119: "End", 120: "F2", 121: "Next", 122: "F1",
    123: "Left", 124: "Right", 125: "Down", 126: "Up",
}


class NullInput:
    """Records events instead of acting on them (tests, simulator)."""

    def __init__(self):
        self.log = []

    def key(self, keycode: int, down: bool):
        self.log.append(("key", keycode, down))

    def mouse(self, x: int, y: int, button: bool):
        self.log.append(("mouse", x, y, button))


class XdotoolInput:
    """Drives an X display with xdotool (sudo apt install xdotool)."""

    def __init__(self, display: str = ":1", scale: tuple[float, float] = (1.0, 1.0)):
        if not shutil.which("xdotool"):
            raise RuntimeError("xdotool is not installed: sudo apt install xdotool")
        self.env = {"DISPLAY": display}
        self.scale = scale
        self.button = False
        self.last_xy = None

    def _run(self, *args):
        subprocess.run(["xdotool", *args], env=self.env, check=False)

    def key(self, keycode: int, down: bool):
        name = MAC_TO_X.get(keycode)
        if name:
            self._run("keydown" if down else "keyup", name)

    def mouse(self, x: int, y: int, button: bool):
        xy = (int(x * self.scale[0]), int(y * self.scale[1]))
        if xy != self.last_xy:
            self._run("mousemove", str(xy[0]), str(xy[1]))
            self.last_xy = xy
        if button != self.button:
            self._run("mousedown" if button else "mouseup", "1")
            self.button = button
