"""Where frames come from.

* XSource     — a live X desktop (on the Pi: Xvfb at 512x342, or a real display,
                scaled down). Uses Pillow's ImageGrab, no extra packages.
* ImageSource — a still picture or a slideshow of pictures.
* DemoSource  — a little animated fake desktop, for testing with no X at all.

Every source returns an RGB numpy array of exactly 512x342.
"""
import glob
import time

import numpy as np
from PIL import Image, ImageDraw, ImageGrab

from . import protocol as P

SIZE = (P.SCREEN_W, P.SCREEN_H)


def fit(img: Image.Image) -> np.ndarray:
    """Letterbox any image into 512x342 on a white background."""
    img = img.convert("RGB")
    if img.size != SIZE:
        img.thumbnail(SIZE, Image.LANCZOS)
        canvas = Image.new("RGB", SIZE, "white")
        canvas.paste(img, ((SIZE[0] - img.width) // 2, (SIZE[1] - img.height) // 2))
        img = canvas
    return np.asarray(img)


class XSource:
    def __init__(self, display: str = ":1"):
        self.display = display

    def grab(self) -> np.ndarray:
        return fit(ImageGrab.grab(xdisplay=self.display))


class ImageSource:
    def __init__(self, pattern: str, seconds: float = 5.0):
        self.paths = sorted(glob.glob(pattern)) or [pattern]
        self.frames = [fit(Image.open(p)) for p in self.paths]
        self.seconds = seconds
        self.t0 = time.monotonic()

    def grab(self) -> np.ndarray:
        i = int((time.monotonic() - self.t0) / self.seconds) % len(self.frames)
        return self.frames[i]


class DemoSource:
    """A fake classic desktop: menu bar, a window with a ticking counter, and
    a little bouncing box. Deterministic per frame number, so tests repeat."""

    def __init__(self):
        self.n = 0

    def frame(self, n: int) -> np.ndarray:
        img = Image.new("RGB", SIZE, (170, 170, 170))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, SIZE[0], 19], fill="white")
        d.line([0, 19, SIZE[0], 19], fill="black")
        d.text((10, 4), "File  Edit  View  Special", fill="black")
        d.rectangle([60, 60, 360, 260], fill="white", outline="black")
        d.rectangle([60, 60, 360, 78], outline="black")
        for yy in range(63, 76, 2):
            d.line([62, yy, 358, yy], fill="black")
        d.rectangle([170, 62, 250, 76], fill="white")
        d.text((180, 64), "BrainSCSI", fill="black")
        d.text((80, 100), f"Frames sent: {n}", fill="black")
        d.text((80, 120), "The Pi does the thinking.", fill="black")
        bx = 80 + (n * 7) % 240
        d.rectangle([bx, 200, bx + 20, 220], fill="black")
        return np.asarray(img)

    def grab(self) -> np.ndarray:
        f = self.frame(self.n)
        self.n += 1
        return f
