"""A model of the Mac side, in Python, for tests and the simulator.

It applies down-packets to a 1-bit screen exactly the way the real 68k client
does, so if the model's screen matches the Pi's frame, the protocol works.
"""
import numpy as np
from PIL import Image

from . import packbits, protocol as P


class MacScreen:
    def __init__(self, width: int = P.SCREEN_W, height: int = P.SCREEN_H):
        self.w, self.h, self.rb = width, height, width // 8
        # Start with random junk: the real screen holds whatever was there.
        self.bits = np.random.default_rng(1).integers(0, 256, (height, self.rb), dtype=np.uint8)
        self.cursor = None
        self.beeps = 0
        self.last_seq = 0

    def apply(self, data: bytes) -> P.Packet:
        pkt = P.decode_packet(data)
        for r in pkt.records:
            if r.type == P.RECT:
                x, y, w, h, enc, _ = P.RECT_HDR.unpack_from(r.payload)
                body = r.payload[P.RECT_HDR.size:]
                rb = w // 8
                if enc == P.ENC_RAW:
                    if len(body) != rb * h:
                        raise ValueError("raw rect size mismatch")
                    rows = [body[i * rb:(i + 1) * rb] for i in range(h)]
                elif enc == P.ENC_PACKBITS:
                    rows = packbits.unpack_rows(body, rb, h)
                else:
                    raise ValueError(f"unknown encoding {enc}")
                bx = x // 8
                for i, row in enumerate(rows):
                    self.bits[y + i, bx:bx + rb] = np.frombuffer(row, dtype=np.uint8)
            elif r.type == P.CURSOR:
                self.cursor = r.payload
            elif r.type == P.BEEP:
                self.beeps += 1
        self.last_seq = pkt.seq
        return pkt

    def image(self, scale: int = 1) -> Image.Image:
        px = np.unpackbits(self.bits, axis=1)[:, :self.w]
        img = Image.fromarray(np.where(px == 1, 0, 255).astype(np.uint8), "L")
        if scale > 1:
            img = img.resize((self.w * scale, self.h * scale), Image.NEAREST)
        return img


def bits_to_image(bits: np.ndarray) -> Image.Image:
    px = np.unpackbits(bits, axis=1)
    return Image.fromarray(np.where(px == 1, 0, 255).astype(np.uint8), "L")
