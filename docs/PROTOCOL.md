# BrainSCSI Link Protocol — v1

This is the conversation between the **Mac** (the SE, acting as a terminal) and the **Pi** (the brain), carried over the SE's SCSI port.

Everything is **big-endian**, which is the 68000's native byte order, so the Mac never has to swap bytes. Every record is padded to an **even length** so the 68000 never does a word access on an odd address (which would crash it with an address error).

---

## 1. The SCSI device

The Pi appears on the bus as one SCSI device:

| Field | Value |
|---|---|
| Default SCSI ID | 5 (configurable) |
| Device type (INQUIRY byte 0) | `0x03` — processor device |
| Vendor (INQUIRY bytes 8–15) | `BRAIN   ` |
| Product (INQUIRY bytes 16–31) | `SCSI LINK       ` |
| Revision (INQUIRY bytes 32–35) | `0001` |

A processor-type device is ignored by the Mac's disk drivers, so the Finder will never try to mount it.

Only four commands are used:

| Command | Opcode | Direction | Purpose |
|---|---|---|---|
| TEST UNIT READY | `0x00` | — | Is the brain alive? |
| INQUIRY | `0x12` | Pi → Mac | Find the brain on the bus |
| SEND | `0x0A` | Mac → Pi | Deliver an **up-packet** (input, floppy data) |
| RECEIVE | `0x08` | Pi → Mac | Collect a **down-packet** (screen, cursor, sound) |

SEND and RECEIVE use the standard processor-device CDB:

```
byte 0   opcode (0x0A or 0x08)
byte 1   0
byte 2-4 transfer length (24-bit, big-endian) — for RECEIVE this is the
         Mac's buffer size; the Pi returns at most this many bytes
byte 5   0 (control)
```

On RECEIVE, the Pi always returns a complete packet, never more than the allocation length. If it has nothing to say it returns a 12-byte header with zero records. If more data is waiting than fits, it sets the `MORE` flag and the Mac polls again immediately.

Because the packet is usually shorter than the allocation, the Mac reads it in two steps inside the same command: first the 12-byte header, then exactly `length` more bytes. The Pi then goes to status phase. This keeps the transfer exact, so the Mac never waits on bytes that aren't coming.

## 2. The loop

The Mac drives everything. Once per pass of its main loop it does:

```
1. SEND     one up-packet  (keyboard + mouse events since last pass, ACK)
2. RECEIVE  one down-packet (changed screen rectangles, cursor, audio...)
3. Apply the down-packet to the screen
4. If the MORE flag was set, go straight back to 2
```

The Pi never has to interrupt the Mac, which keeps the Mac side simple and avoids SCSI reselection (which the SE's SCSI Manager doesn't support well).

## 3. Packet layout

Both directions use the same 12-byte header followed by records.

```
offset size  field
0      2     magic       'BS' (0x42 0x53)
2      1     version     1
3      1     flags       bit 0 = MORE   (down only: more data waiting)
                         bit 1 = RESET  (down only: Mac should clear screen state)
4      2     seq         packet sequence number, wraps at 65535
6      2     count       number of records that follow
8      4     length      total bytes after the header
```

Each record:

```
offset size  field
0      1     type
1      1     reserved (0)
2      2     length      payload bytes (not counting this 4-byte record header)
4      n     payload, then 1 zero pad byte if n is odd
```

### 3.1 Up records (Mac → Pi)

| Type | Name | Payload |
|---|---|---|
| `0x01` | HELLO | `u16 proto`, `u16 width`, `u16 height`, `u16 rowBytes`, `u16 machine`, `u16 features` |
| `0x02` | KEY | `u8 keycode` (Mac virtual key code), `u8 down` (1/0), `u16 modifiers` (Toolbox `EventRecord.modifiers`) |
| `0x03` | MOUSE | `i16 x`, `i16 y` (absolute, screen pixels), `u8 buttons` (bit 0 = button down), `u8 0` |
| `0x04` | ACK | `u16 seq` — last down-packet the Mac fully applied |
| `0x10` | FLOPPY_STATUS | `u8 drive`, `u8 inserted`, `u16 blocks` (800 = 400K, 1600 = 800K, 2880 = 1.4M) |
| `0x11` | FLOPPY_DATA | `u8 drive`, `u8 0`, `u16 firstBlock`, `u16 blockCount`, then `blockCount × 512` bytes |

`features` bits: 0 = has sound, 1 = has floppy drive 1, 2 = has floppy drive 2.

The Mac sends HELLO as the first record of its first packet, and again whenever it restarts. When the Pi sees HELLO it sends a full screen next.

### 3.2 Down records (Pi → Mac)

| Type | Name | Payload |
|---|---|---|
| `0x81` | RECT | `u16 x`, `u16 y`, `u16 w`, `u16 h`, `u8 encoding`, `u8 0`, then pixel data |
| `0x82` | CURSOR | Toolbox `Cursor` record: 32 bytes `data`, 32 bytes `mask`, `i16 hotV`, `i16 hotH` (68 bytes) |
| `0x83` | BEEP | `u16 duration` (ticks) |
| `0x84` | AUDIO | `u16 sampleRate` (Hz), then 8-bit unsigned mono samples |
| `0x85` | FLOPPY_REQ | `u8 drive`, `u8 op` (0 = read, 1 = eject, 2 = status), `u16 firstBlock`, `u16 blockCount` |
| `0x8F` | BYE | none — the Pi is shutting down |

#### RECT pixel data

- `x` and `w` are always multiples of **16 pixels**, so every row starts and ends on a 68000 word boundary.
- Pixels are 1 bit each, **1 = black**, which is exactly the Mac's screen format.
- `encoding 0` — **raw**: `h` rows of `w/8` bytes.
- `encoding 1` — **PackBits**: each row is compressed separately with Apple's PackBits and the rows are concatenated. The Mac decompresses with the Toolbox's own `UnpackBits` routine, row by row, straight into screen memory.

The Pi picks whichever encoding is smaller for each rectangle.

## 4. How the Pi decides what to send

1. Grab a frame from the desktop at **512 × 342**.
2. Convert to 1-bit — ordered dithering for live desktops, or **Atkinson dithering** (Bill Atkinson's algorithm from the original Mac) for photos.
3. Split the screen into **32 × 32 tiles** (16 across, 11 down; the bottom row is 22 pixels tall).
4. Compare each tile with what the Mac already has. Join neighbouring changed tiles in the same tile row into one rectangle.
5. Encode each rectangle and pack as many as fit into the Mac's receive buffer. Anything left over is sent next time with `MORE` set.

The Pi keeps its own copy of exactly what the Mac's screen shows. SCSI delivery is reliable, so a rectangle counts as delivered as soon as it goes out. If the Mac restarts (new HELLO), the Pi marks the whole screen unknown and sends everything again with the `RESET` flag. ACK is carried for future use (for example, retransmitting after a SCSI error) and is not needed in v1.

**Dithering choice matters for speed.** Ordered (Bayer) dithering is the live default because each pixel depends only on itself: change one corner and nothing else moves, so updates stay tiny. Atkinson error diffusion looks better on photos, but its error spreads, so a small change can ripple across the screen and resend far more. Use Atkinson for photos and slideshows.

## 5. Speed budget

| | |
|---|---|
| Full SE screen, 1-bit | 512 × 342 ÷ 8 = **21,888 bytes** |
| SE SCSI (NCR 5380, blind transfers) | roughly **500–1,000 KB/s** in practice |
| Full-screen redraws, raw | about **20–40 per second** at the link, fewer after the 68000 copies to screen |
| Typing a letter | one or two 32 × 32 tiles ≈ **130–260 bytes** |

So the link is fast enough for a full redraw several times a second, and ordinary desktop use is mostly tiny updates. The 8 MHz 68000 copying and unpacking bytes is the real limit, which is why the Pi does all the heavy work and hands the Mac data it can drop straight onto the screen.

## 6. Development transport (TCP)

Until the PiSCSI device plugin exists, the Pi server also speaks the same packets over TCP so the whole pipeline can be tested on any computer with `sim_mac.py`. Each SCSI command becomes:

```
Client → server:  'S' u32 length, then up-packet        (SEND)
                  'R' u32 allocation                    (RECEIVE)
Server → client:  u32 length, then down-packet          (reply to 'R' only)
```

The future PiSCSI device ("SCBS") is a thin shim: it turns each SEND/RECEIVE CDB into exactly these messages on a local Unix socket, so the server code does not change when the real SCSI hardware arrives.
