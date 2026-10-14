# BrainSCSI — Mac SE client

The little program that runs on the Mac. It finds the Pi on the SCSI bus, sends your keyboard and mouse, and draws the screen pieces the Pi sends back straight into screen memory.

Works on any 68k Mac with a SCSI port and a 512 × 342 screen (Plus, SE, SE/30, Classic, Classic II). System 6.0.x or System 7.

> **Status:** starter code. It passes a syntax check against the Toolbox interfaces but hasn't run on real hardware yet; the Pi-side SCSI device it talks to is the next milestone.

## Build

1. Build [Retro68](https://github.com/autc04/Retro68) once (it builds a 68k GCC; takes a while).
2. Then:

```sh
cd mac
mkdir build && cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=<Retro68-build>/toolchain/m68k-apple-macos/cmake/retro68.toolchain.cmake
make
```

You get `BrainSCSI.bin` (MacBinary), `BrainSCSI.dsk` (a disk image), and `BrainSCSI.APPL`. Copy the `.dsk` to a PiSCSI/BlueSCSI image folder or a Floppy Emu, or write it to a real floppy.

## Use

1. Plug the Pi (with its PiSCSI board) into the SE's DB-25 SCSI port and power it up.
2. Double-click **BrainSCSI**. It scans IDs 0–6 for a device named `BRAIN`.
3. The SE's screen becomes the Pi's desktop. Your keyboard and mouse drive the Pi.

**Quit:** hold **⌘ Command + ⌥ Option + ⇧ Shift** and press **Q**.

## How it works

| File | Job |
|---|---|
| `src/link.c` | SCSI Manager calls: INQUIRY to find the Pi, SEND and RECEIVE for packets. Reads each packet as header first, then exactly the body length. |
| `src/main.c` | The main loop: read keys with `GetKeys` (so modifiers and key-ups are seen), read the mouse, send, receive, draw. |
| `src/link.h` | Packet and record layouts from [docs/PROTOCOL.md](../docs/PROTOCOL.md). |

Drawing is cheap on purpose: every rectangle is word-aligned, already 1-bit, and either raw or PackBits — which the Mac's ROM unpacks with `UnpackBits`. The 68000 never dithers, scales, or decodes anything fancy.

`BS_USE_BLIND` in `link.c` turns on blind SCSI transfers for big packets. They're much faster on the SE's NCR 5380. If you ever see the Mac freeze mid-transfer, set it to 0.
