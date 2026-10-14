"""BrainSCSI link protocol v1 — packet encode/decode. See docs/PROTOCOL.md."""
import struct
from dataclasses import dataclass

MAGIC = b"BS"
VERSION = 1
HEADER = struct.Struct(">2sBBHHI")      # magic, version, flags, seq, count, length
REC_HDR = struct.Struct(">BBH")         # type, reserved, length

FLAG_MORE = 0x01
FLAG_RESET = 0x02

# Up (Mac -> Pi)
HELLO, KEY, MOUSE, ACK = 0x01, 0x02, 0x03, 0x04
FLOPPY_STATUS, FLOPPY_DATA = 0x10, 0x11
# Down (Pi -> Mac)
RECT, CURSOR, BEEP, AUDIO, FLOPPY_REQ, BYE = 0x81, 0x82, 0x83, 0x84, 0x85, 0x8F

ENC_RAW, ENC_PACKBITS = 0, 1

SCREEN_W, SCREEN_H = 512, 342
MAX_RECORD = 0xFFFF


@dataclass
class Record:
    type: int
    payload: bytes

    def encoded_size(self) -> int:
        n = len(self.payload)
        return REC_HDR.size + n + (n & 1)


def encode_record(r: Record) -> bytes:
    if len(r.payload) > MAX_RECORD:
        raise ValueError("record too large")
    out = REC_HDR.pack(r.type, 0, len(r.payload)) + r.payload
    if len(r.payload) & 1:
        out += b"\0"
    return out


def encode_packet(records: list[Record], seq: int = 0, flags: int = 0) -> bytes:
    body = b"".join(encode_record(r) for r in records)
    return HEADER.pack(MAGIC, VERSION, flags, seq & 0xFFFF, len(records), len(body)) + body


@dataclass
class Packet:
    flags: int
    seq: int
    records: list[Record]


def decode_packet(data: bytes) -> Packet:
    if len(data) < HEADER.size:
        raise ValueError("short packet")
    magic, ver, flags, seq, count, length = HEADER.unpack_from(data)
    if magic != MAGIC or ver != VERSION:
        raise ValueError("bad magic/version")
    if HEADER.size + length > len(data):
        raise ValueError("truncated packet")
    off, recs = HEADER.size, []
    for _ in range(count):
        t, _res, n = REC_HDR.unpack_from(data, off)
        off += REC_HDR.size
        recs.append(Record(t, bytes(data[off:off + n])))
        off += n + (n & 1)
    if off != HEADER.size + length:
        raise ValueError("length mismatch")
    return Packet(flags, seq, recs)


# ---- typed helpers -------------------------------------------------------

def hello(width=SCREEN_W, height=SCREEN_H, row_bytes=64, machine=0, features=0) -> Record:
    return Record(HELLO, struct.pack(">HHHHHH", VERSION, width, height, row_bytes, machine, features))


def key(keycode: int, down: bool, modifiers: int = 0) -> Record:
    return Record(KEY, struct.pack(">BBH", keycode, 1 if down else 0, modifiers))


def mouse(x: int, y: int, button: bool) -> Record:
    return Record(MOUSE, struct.pack(">hhBB", x, y, 1 if button else 0, 0))


def ack(seq: int) -> Record:
    return Record(ACK, struct.pack(">H", seq & 0xFFFF))


RECT_HDR = struct.Struct(">HHHHBB")


def rect(x: int, y: int, w: int, h: int, encoding: int, data: bytes) -> Record:
    if x % 16 or w % 16:
        raise ValueError("x and w must be multiples of 16")
    return Record(RECT, RECT_HDR.pack(x, y, w, h, encoding, 0) + data)


def beep(ticks: int = 10) -> Record:
    return Record(BEEP, struct.pack(">H", ticks))
