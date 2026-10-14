"""Work out what changed on screen and pack it into down-packets.

The encoder keeps a copy of exactly what the Mac's screen shows. Each call
compares a new 1-bit frame against that copy in 32x32 tiles, joins changed
tiles that sit next to each other in a tile row, trims each run to the rows
that actually changed, and packs as many rectangles as fit in the Mac's
receive buffer. Anything that doesn't fit stays dirty and goes next time,
with the MORE flag set so the Mac polls again straight away.

SCSI delivery is reliable, so the copy is updated as soon as a rectangle is
packed. If the Mac restarts it sends HELLO and we call reset(), which marks
the whole screen unknown and forces a full redraw.
"""
import numpy as np

from . import packbits, protocol as P

TILE = 32  # pixels; 4 bytes wide, a multiple of 16 so rows stay word-aligned


class Encoder:
    def __init__(self, width: int = P.SCREEN_W, height: int = P.SCREEN_H):
        if width % TILE:
            raise ValueError("width must be a multiple of 32")
        self.w, self.h = width, height
        self.rb = width // 8
        self.ncols = width // TILE
        self.mac = np.zeros((height, self.rb), dtype=np.uint8)
        # unknown[row, tile column] = we don't know what the Mac shows there.
        self.unknown = np.ones((height, self.ncols), dtype=bool)
        self.send_reset = True
        self.seq = 0
        self.stats = {"packets": 0, "bytes": 0, "rects": 0}

    def reset(self):
        """The Mac restarted (HELLO): its screen is unknown, redraw everything."""
        self.unknown[:] = True
        self.send_reset = True

    # -- finding changes ---------------------------------------------------
    def dirty_map(self, frame: np.ndarray) -> np.ndarray:
        """Bool (rows, tile columns): True where the Mac needs new pixels."""
        if frame.shape != self.mac.shape:
            raise ValueError(f"frame must be {self.mac.shape}, got {frame.shape}")
        diff = (frame != self.mac).reshape(self.h, self.ncols, TILE // 8).any(axis=2)
        return diff | self.unknown

    def dirty_rects(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Return (x, y, w, h) in pixels for every changed run of tiles."""
        dmap = self.dirty_map(frame)
        rects = []
        for ty in range(0, self.h, TILE):
            y1 = min(ty + TILE, self.h)
            band = dmap[ty:y1]
            cols = band.any(axis=0)
            c = 0
            while c < self.ncols:
                if not cols[c]:
                    c += 1
                    continue
                start = c
                while c < self.ncols and cols[c]:
                    c += 1
                rows = np.nonzero(band[:, start:c].any(axis=1))[0]
                r0, r1 = ty + int(rows[0]), ty + int(rows[-1]) + 1
                rects.append((start * TILE, r0, (c - start) * TILE, r1 - r0))
        return rects

    # -- encoding ----------------------------------------------------------
    @staticmethod
    def encode_rect(frame: np.ndarray, x: int, y: int, w: int, h: int) -> P.Record:
        bx0, bx1 = x // 8, (x + w) // 8
        rows = [frame[r, bx0:bx1].tobytes() for r in range(y, y + h)]
        raw = b"".join(rows)
        packed = packbits.pack_rows(rows)
        if len(packed) < len(raw):
            return P.rect(x, y, w, h, P.ENC_PACKBITS, packed)
        return P.rect(x, y, w, h, P.ENC_RAW, raw)

    def build_packet(self, frame: np.ndarray, budget: int = 32768,
                     extra: list[P.Record] | None = None) -> bytes:
        """Build one down-packet no bigger than `budget` bytes."""
        records = list(extra or [])
        used = P.HEADER.size + sum(r.encoded_size() for r in records)
        flags = P.FLAG_RESET if self.send_reset else 0
        self.send_reset = False
        more = False
        for (x, y, w, h) in self.dirty_rects(frame):
            # Split a run into row strips if it won't fit in what's left.
            strip = h
            while strip > 0:
                rec = self.encode_rect(frame, x, y, w, strip)
                if used + rec.encoded_size() <= budget and len(rec.payload) <= P.MAX_RECORD:
                    break
                strip //= 2
            if strip == 0:
                more = True
                continue
            records.append(rec)
            used += rec.encoded_size()
            bx0, bx1 = x // 8, (x + w) // 8
            self.mac[y:y + strip, bx0:bx1] = frame[y:y + strip, bx0:bx1]
            self.unknown[y:y + strip, x // TILE:(x + w) // TILE] = False
            self.stats["rects"] += 1
            if strip < h:
                more = True
        if more:
            flags |= P.FLAG_MORE
        self.seq = (self.seq + 1) & 0xFFFF
        pkt = P.encode_packet(records, self.seq, flags)
        self.stats["packets"] += 1
        self.stats["bytes"] += len(pkt)
        return pkt
