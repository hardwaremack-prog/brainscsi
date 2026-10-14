"""The brain: answers the Mac's SEND and RECEIVE commands.

`Brain` knows nothing about wires — it takes up-packets and hands back
down-packets. `serve()` puts it on a TCP or Unix socket using the
development transport in docs/PROTOCOL.md section 6. The PiSCSI device
plugin will talk to the same socket, so this code doesn't change when the
real SCSI hardware is attached.

Run on the Pi:
    python3 -m brainscsi.server --source x --display :1 --listen unix:/run/brainscsi.sock
Try it anywhere:
    python3 -m brainscsi.server --source demo --listen tcp:127.0.0.1:5150
"""
import argparse
import os
import socket
import struct
import time

from . import dither, protocol as P
from .encoder import Encoder
from .inputs import NullInput


class Brain:
    def __init__(self, source, inputs=None, mode: str = "ordered", max_fps: float = 15.0):
        self.source = source
        self.inputs = inputs or NullInput()
        self.mode = mode
        self.enc = Encoder()
        self.min_interval = 1.0 / max_fps
        self.frame = None
        self.frame_t = 0.0
        self.hello = None
        self.pending: list[P.Record] = []

    # Mac -> Pi
    def handle_send(self, data: bytes):
        pkt = P.decode_packet(data)
        for r in pkt.records:
            if r.type == P.HELLO:
                self.hello = struct.unpack(">HHHHHH", r.payload)
                self.enc.reset()
                self.frame = None
            elif r.type == P.KEY:
                code, down, _mods = struct.unpack(">BBH", r.payload)
                self.inputs.key(code, bool(down))
            elif r.type == P.MOUSE:
                x, y, buttons, _ = struct.unpack(">hhBB", r.payload)
                self.inputs.mouse(x, y, bool(buttons & 1))
            # ACK and floppy records are accepted and ignored in v1.

    # Pi -> Mac
    def handle_receive(self, alloc: int) -> bytes:
        now = time.monotonic()
        if self.frame is None or now - self.frame_t >= self.min_interval:
            self.frame = dither.dither(self.source.grab(), self.mode)
            self.frame_t = now
        extra, self.pending = self.pending, []
        return self.enc.build_packet(self.frame, budget=alloc, extra=extra)

    def queue(self, record: P.Record):
        self.pending.append(record)


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("client went away")
        buf += chunk
    return bytes(buf)


def handle_connection(brain: Brain, conn: socket.socket):
    while True:
        op = _recv_exact(conn, 1)
        (n,) = struct.unpack(">I", _recv_exact(conn, 4))
        if op == b"S":
            brain.handle_send(_recv_exact(conn, n))
        elif op == b"R":
            out = brain.handle_receive(n)
            conn.sendall(struct.pack(">I", len(out)) + out)
        else:
            raise ConnectionError(f"bad op {op!r}")


def make_listener(spec: str) -> socket.socket:
    kind, _, addr = spec.partition(":")
    if kind == "unix":
        if os.path.exists(addr):
            os.unlink(addr)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(addr)
    elif kind == "tcp":
        host, _, port = addr.rpartition(":")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host or "127.0.0.1", int(port)))
    else:
        raise ValueError("listen spec must be unix:/path or tcp:host:port")
    s.listen(1)
    return s


def serve(brain: Brain, spec: str):
    lst = make_listener(spec)
    print(f"BrainSCSI listening on {spec}")
    while True:
        conn, _ = lst.accept()
        print("Mac connected")
        try:
            handle_connection(brain, conn)
        except ConnectionError as e:
            print(f"Mac disconnected: {e}")
        finally:
            conn.close()


def main(argv=None):
    from . import sources
    ap = argparse.ArgumentParser(description="BrainSCSI screen server")
    ap.add_argument("--source", choices=["demo", "x", "image"], default="demo")
    ap.add_argument("--display", default=":1", help="X display for --source x")
    ap.add_argument("--image", help="image file or glob for --source image")
    ap.add_argument("--dither", choices=list(dither.MODES), default="ordered")
    ap.add_argument("--fps", type=float, default=15.0)
    ap.add_argument("--listen", default="tcp:127.0.0.1:5150")
    ap.add_argument("--no-input", action="store_true", help="don't drive the desktop")
    a = ap.parse_args(argv)

    if a.source == "x":
        src = sources.XSource(a.display)
    elif a.source == "image":
        src = sources.ImageSource(a.image)
    else:
        src = sources.DemoSource()

    inputs = None
    if a.source == "x" and not a.no_input:
        from .inputs import XdotoolInput
        inputs = XdotoolInput(a.display)

    serve(Brain(src, inputs, a.dither, a.fps), a.listen)


if __name__ == "__main__":
    main()
