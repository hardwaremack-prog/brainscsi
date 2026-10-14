#!/usr/bin/env python3
"""Pretend to be the Mac SE and see what BrainSCSI would look like.

Runs the full pipeline — grab, dither, dirty tiles, PackBits, packets — and
applies every packet to a model of the SE's screen, exactly as the real 68k
client does. Prints how many bytes crossed the link and estimates how that
would feel on a real SE.

    python3 sim_mac.py                              # built-in demo desktop
    python3 sim_mac.py --image photo.jpg --dither atkinson
    python3 sim_mac.py --connect tcp:127.0.0.1:5150  # talk to a running server
    python3 sim_mac.py --gif out.gif                # save an animation
"""
import argparse
import os
import socket
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brainscsi import protocol as P, sources  # noqa: E402
from brainscsi.macmodel import MacScreen  # noqa: E402
from brainscsi.server import Brain  # noqa: E402

# Rough Mac SE numbers, on the cautious side:
LINK_BPS = 600_000        # NCR 5380 blind transfers, bytes/second
DRAW_BPS = 400_000        # 8 MHz 68000 writing screen bytes (UnpackBits / copy)
POLL_COST = 0.004         # SEND + RECEIVE command overhead per poll, seconds


class SocketLink:
    def __init__(self, spec):
        kind, _, addr = spec.partition(":")
        if kind == "unix":
            self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.s.connect(addr)
        else:
            host, _, port = addr.rpartition(":")
            self.s = socket.create_connection((host, int(port)))

    def send(self, data):
        self.s.sendall(b"S" + struct.pack(">I", len(data)) + data)

    def receive(self, alloc):
        self.s.sendall(b"R" + struct.pack(">I", alloc))
        (n,) = struct.unpack(">I", self._exact(4))
        return self._exact(n)

    def _exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            c = self.s.recv(n - len(buf))
            if not c:
                raise ConnectionError("server closed")
            buf += c
        return bytes(buf)


class LocalLink:
    def __init__(self, brain):
        self.brain = brain

    def send(self, data):
        self.brain.handle_send(data)

    def receive(self, alloc):
        return self.brain.handle_receive(alloc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connect", help="unix:/path or tcp:host:port of a running server")
    ap.add_argument("--image", help="use this image (or glob) instead of the demo desktop")
    ap.add_argument("--dither", default="ordered", choices=["ordered", "atkinson", "threshold"])
    ap.add_argument("--frames", type=int, default=30, help="screen updates to simulate")
    ap.add_argument("--buffer", type=int, default=32768, help="Mac receive buffer, bytes")
    ap.add_argument("--out", default="se_screen.png")
    ap.add_argument("--gif", help="also save every update as an animated GIF")
    a = ap.parse_args()

    if a.connect:
        link = SocketLink(a.connect)
    else:
        src = sources.ImageSource(a.image) if a.image else sources.DemoSource()
        link = LocalLink(Brain(src, mode=a.dither, max_fps=1e9))

    mac = MacScreen()
    seq, frames, sizes, drawn, polls = 1, [], [], [], []
    link.send(P.encode_packet([P.hello()], seq))

    for i in range(a.frames):
        # Poll until the Pi says there's nothing more for this frame.
        update = pix = n = 0
        while True:
            pkt_bytes = link.receive(a.buffer)
            pkt = mac.apply(pkt_bytes)
            update += len(pkt_bytes)
            n += 1
            for r in pkt.records:
                if r.type == P.RECT:
                    _, _, w, h, _, _ = P.RECT_HDR.unpack_from(r.payload)
                    pix += w * h // 8
            seq += 1
            # A little mouse wiggle so the input path gets exercised too.
            link.send(P.encode_packet([P.mouse(100 + i * 5, 150, False), P.ack(pkt.seq)], seq))
            if not pkt.flags & P.FLAG_MORE:
                break
        sizes.append(update)
        drawn.append(pix)
        polls.append(n)
        if a.gif:
            frames.append(mac.image(2).convert("P"))

    mac.image(2).save(a.out)
    if a.gif and frames:
        frames[0].save(a.gif, save_all=True, append_images=frames[1:], duration=100, loop=0)

    def se_time(i):
        return sizes[i] / LINK_BPS + drawn[i] / DRAW_BPS + polls[i] * POLL_COST

    full = P.SCREEN_W * P.SCREEN_H // 8
    print(f"First full screen : {sizes[0]:7,} bytes over the link (raw would be {full:,})")
    print(f"                    ~{se_time(0) * 1000:.0f} ms to draw on a real SE")
    if len(sizes) > 1:
        avg_b = sum(sizes[1:]) / (len(sizes) - 1)
        avg_t = sum(se_time(i) for i in range(1, len(sizes))) / (len(sizes) - 1)
        print(f"Average update    : {avg_b:7,.0f} bytes, ~{avg_t * 1000:.0f} ms on a real SE "
              f"(about {1 / avg_t:.0f} updates/sec)")
    print(f"Saved {a.out}" + (f" and {a.gif}" if a.gif else ""))


if __name__ == "__main__":
    main()
