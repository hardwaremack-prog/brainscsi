"""Apple PackBits — the same run-length scheme the Mac Toolbox's UnpackBits reads.

Each chunk starts with a signed header byte n:
  0..127    -> copy the next n+1 bytes literally
  -1..-127  -> repeat the next byte 1-n times (2..128)
  -128      -> no-op (never emitted here)
"""


def pack(data: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        # Measure the run starting at i.
        run = 1
        while i + run < n and run < 128 and data[i + run] == data[i]:
            run += 1
        if run >= 2:
            out.append((257 - run) & 0xFF)  # -(run-1) as a signed byte
            out.append(data[i])
            i += run
            continue
        # Literal: gather bytes until a run of 2+ begins or we hit 128.
        start = i
        i += 1
        while i < n and i - start < 128:
            if i + 1 < n and data[i] == data[i + 1]:
                break
            i += 1
        out.append(i - start - 1)
        out += data[start:i]
    return bytes(out)


def unpack(data: bytes, size: int, offset: int = 0) -> tuple[bytes, int]:
    """Unpack exactly `size` bytes starting at `offset`.

    Returns (bytes, new_offset) — like UnpackBits advancing its source pointer.
    """
    out = bytearray()
    i = offset
    while len(out) < size:
        h = data[i]
        i += 1
        if h < 128:
            cnt = h + 1
            out += data[i:i + cnt]
            i += cnt
        elif h > 128:
            out += bytes([data[i]]) * (257 - h)
            i += 1
        # h == 128: no-op
    if len(out) != size:
        raise ValueError("PackBits row overran its length")
    return bytes(out), i


def pack_rows(rows: list[bytes]) -> bytes:
    """Pack each row on its own, like the Mac does for bitmaps."""
    return b"".join(pack(r) for r in rows)


def unpack_rows(data: bytes, row_bytes: int, height: int) -> list[bytes]:
    rows, off = [], 0
    for _ in range(height):
        row, off = unpack(data, row_bytes, off)
        rows.append(row)
    if off != len(data):
        raise ValueError("trailing bytes after PackBits rows")
    return rows
