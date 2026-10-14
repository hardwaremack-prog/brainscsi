"""Turn a grayscale frame into the SE's 1-bit screen format.

Two modes:

* ``ordered`` — 4x4 Bayer dither. Fast (pure numpy) and, crucially, *stable*:
  a pixel's result depends only on itself, so changing one corner of the
  screen never changes pixels anywhere else. That keeps the dirty-tile count
  tiny, which matters far more over SCSI than prettiness. Default for live
  desktops.

* ``atkinson`` — Bill Atkinson's error diffusion, the look of MacPaint and
  HyperCard. Beautiful for photos, but error spreads, so a small change can
  ripple across the frame. Use for still images or slow-changing content.

Output: numpy uint8 array, shape (h, w//8), 1 bit = black, MSB = leftmost
pixel — the Mac's own screen layout.
"""
import numpy as np

_BAYER4 = (np.array([[0, 8, 2, 10],
                     [12, 4, 14, 6],
                     [3, 11, 1, 9],
                     [15, 7, 13, 5]], dtype=np.float32) + 0.5) / 16.0 * 255.0


def to_gray(rgb: np.ndarray) -> np.ndarray:
    """RGB(A) uint8 (h, w, 3|4) -> float32 luminance 0..255."""
    if rgb.ndim == 2:
        return rgb.astype(np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (0.299 * r + 0.587 * g + 0.114 * b).astype(np.float32)


def ordered(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape
    thresh = np.tile(_BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]
    black = gray < thresh
    return np.packbits(black, axis=1)


def threshold(gray: np.ndarray, level: float = 128.0) -> np.ndarray:
    return np.packbits(gray < level, axis=1)


def atkinson(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape
    # Work on Python lists with 2 rows of padding below and 2 cols each side.
    buf = [list(map(float, row)) + [0.0, 0.0] for row in gray]
    buf += [[0.0] * (w + 2) for _ in range(2)]
    black = np.zeros((h, w), dtype=bool)
    for y in range(h):
        row, nxt, nxt2 = buf[y], buf[y + 1], buf[y + 2]
        brow = black[y]
        for x in range(w):
            old = row[x]
            if old < 128.0:
                brow[x] = True
                err = old / 8.0
            else:
                err = (old - 255.0) / 8.0
            if err:
                row[x + 1] += err
                row[x + 2] += err
                if x:
                    nxt[x - 1] += err
                nxt[x] += err
                nxt[x + 1] += err
                nxt2[x] += err
    return np.packbits(black, axis=1)


MODES = {"ordered": ordered, "atkinson": atkinson, "threshold": threshold}


def dither(rgb: np.ndarray, mode: str = "ordered") -> np.ndarray:
    return MODES[mode](to_gray(rgb))
