"""Run with:  python3 -m unittest discover -s tests   (from the pi/ folder)"""
import os
import socket
import sys
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brainscsi import dither, packbits, protocol as P, sources  # noqa: E402
from brainscsi.encoder import Encoder  # noqa: E402
from brainscsi.inputs import NullInput  # noqa: E402
from brainscsi.macmodel import MacScreen  # noqa: E402
from brainscsi.server import Brain, handle_connection, make_listener  # noqa: E402


class PackBitsTests(unittest.TestCase):
    def test_round_trip(self):
        rng = np.random.default_rng(0)
        cases = [b"", b"\x00", b"\xff" * 300, bytes(range(256)) * 2,
                 b"\xaa\xaa\x01\x02\x02\x02\x03" * 40]
        cases += [rng.integers(0, 3, rng.integers(1, 200)).astype(np.uint8).tobytes() for _ in range(300)]
        for c in cases:
            packed = packbits.pack(c)
            out, off = packbits.unpack(packed, len(c))
            self.assertEqual(out, c)
            self.assertEqual(off, len(packed))

    def test_known_apple_example(self):
        # The example from Apple Technical Note TN1023.
        unpacked = bytes.fromhex("AAAAAA80002AAAAAAAAA80002A22" + "AA" * 10)
        out, _ = packbits.unpack(bytes.fromhex("FEAA0280002AFDAA0380002A22F7AA"), len(unpacked))
        self.assertEqual(out, unpacked)
        # Our packer round-trips it too.
        self.assertEqual(packbits.unpack(packbits.pack(unpacked), len(unpacked))[0], unpacked)

    def test_white_row_is_tiny(self):
        self.assertEqual(packbits.pack(b"\x00" * 64), b"\xc1\x00")  # 64 x 0x00 in 2 bytes


class DitherTests(unittest.TestCase):
    def test_shapes_and_extremes(self):
        white = np.full((342, 512, 3), 255, np.uint8)
        black = np.zeros((342, 512, 3), np.uint8)
        for mode in dither.MODES:
            w, b = dither.dither(white, mode), dither.dither(black, mode)
            self.assertEqual(w.shape, (342, 64))
            self.assertEqual(int(w.sum()), 0, mode)          # white -> all bits clear
            self.assertTrue((b == 0xFF).all(), mode)          # black -> all bits set

    def test_mid_gray_is_half_black(self):
        gray = np.full((64, 64, 3), 128, np.uint8)
        for mode in ("ordered", "atkinson"):
            bits = np.unpackbits(dither.dither(gray, mode), axis=1)
            self.assertAlmostEqual(bits.mean(), 0.5, delta=0.06, msg=mode)

    def test_ordered_is_local(self):
        # Changing one corner must not change pixels elsewhere (keeps updates small).
        img = np.asarray(sources.DemoSource().frame(0)).copy()
        a = dither.dither(img, "ordered")
        img[300:340, 450:510] = 0
        b = dither.dither(img, "ordered")
        changed = np.argwhere(a != b)
        self.assertTrue((changed[:, 0] >= 300).all() and (changed[:, 1] * 8 >= 448).all())


class ProtocolTests(unittest.TestCase):
    def test_packet_round_trip_and_alignment(self):
        recs = [P.hello(), P.key(0, True, 0x0100), P.mouse(-1, 400, True),
                P.Record(P.AUDIO, b"\x80" * 7)]
        data = P.encode_packet(recs, seq=65535, flags=P.FLAG_MORE)
        self.assertEqual(len(data) % 2, 0)
        pkt = P.decode_packet(data)
        self.assertEqual(pkt.seq, 65535)
        self.assertEqual(pkt.flags, P.FLAG_MORE)
        self.assertEqual([r.payload for r in pkt.records], [r.payload for r in recs])

    def test_rect_must_be_word_aligned(self):
        with self.assertRaises(ValueError):
            P.rect(8, 0, 16, 1, 0, b"\0\0")


class EncoderTests(unittest.TestCase):
    def frames(self, n, mode="ordered"):
        src = sources.DemoSource()
        return [dither.dither(src.frame(i), mode) for i in range(n)]

    def run_link(self, frames, budget):
        enc, mac = Encoder(), MacScreen()
        sizes = []
        for f in frames:
            total = 0
            for _ in range(200):
                data = enc.build_packet(f, budget)
                self.assertLessEqual(len(data), budget)
                pkt = mac.apply(data)
                total += len(data)
                if not pkt.flags & P.FLAG_MORE:
                    break
            else:
                self.fail("never finished sending a frame")
            np.testing.assert_array_equal(mac.bits, f)
            sizes.append(total)
        return sizes

    def test_mac_screen_matches_every_frame(self):
        sizes = self.run_link(self.frames(12), 32768)
        self.assertLess(sizes[0], 21888)            # first screen compresses
        self.assertLess(max(sizes[1:]), 2500)       # later updates are small

    def test_small_buffer_uses_more_flag(self):
        # A 2 KB buffer forces strips and MORE, but the screen still ends up right.
        self.run_link(self.frames(4), 2048)

    def test_atkinson_and_photo_noise(self):
        rng = np.random.default_rng(3)
        noise = rng.integers(0, 256, (342, 512, 3), dtype=np.uint8)
        self.run_link([dither.dither(noise, "ordered"), dither.dither(noise, "atkinson")], 32768)

    def test_unchanged_frame_sends_nothing(self):
        f = self.frames(1)[0]
        enc = Encoder()
        enc.build_packet(f)
        pkt = P.decode_packet(enc.build_packet(f))
        self.assertEqual(pkt.records, [])

    def test_reset_redraws_everything(self):
        f = self.frames(1)[0]
        enc = Encoder()
        enc.build_packet(f)
        enc.reset()
        pkt = P.decode_packet(enc.build_packet(f))
        self.assertTrue(pkt.flags & P.FLAG_RESET)
        area = sum(P.RECT_HDR.unpack_from(r.payload)[2] * P.RECT_HDR.unpack_from(r.payload)[3]
                   for r in pkt.records)
        self.assertEqual(area, 512 * 342)


class ServerTests(unittest.TestCase):
    def test_tcp_round_trip_with_input(self):
        import struct
        inputs = NullInput()
        brain = Brain(sources.DemoSource(), inputs, max_fps=1000)
        lst = make_listener("tcp:127.0.0.1:0")
        port = lst.getsockname()[1]

        def run():
            conn, _ = lst.accept()
            try:
                handle_connection(brain, conn)
            except ConnectionError:
                pass
            conn.close()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        s = socket.create_connection(("127.0.0.1", port))

        def send(data):
            s.sendall(b"S" + struct.pack(">I", len(data)) + data)

        def recv(alloc):
            s.sendall(b"R" + struct.pack(">I", alloc))
            n = struct.unpack(">I", s.recv(4, socket.MSG_WAITALL))[0]
            return s.recv(n, socket.MSG_WAITALL)

        send(P.encode_packet([P.hello(), P.key(12, True), P.key(12, False), P.mouse(10, 20, True)], 1))
        mac = MacScreen()
        pkt = mac.apply(recv(32768))
        self.assertTrue(pkt.flags & P.FLAG_RESET)
        self.assertEqual(inputs.log, [("key", 12, True), ("key", 12, False), ("mouse", 10, 20, True)])
        s.close()
        t.join(2)
        lst.close()


if __name__ == "__main__":
    unittest.main()
