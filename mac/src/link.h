/* BrainSCSI link — talking to the Pi over the classic SCSI Manager.
   Protocol: docs/PROTOCOL.md. All fields big-endian (native on 68k). */
#ifndef BRAINSCSI_LINK_H
#define BRAINSCSI_LINK_H

#include <Types.h>

#define BS_VERSION     1
#define BS_HEADER_SIZE 12
#define BS_FLAG_MORE   0x01
#define BS_FLAG_RESET  0x02

/* Up (Mac -> Pi) */
#define BS_HELLO   0x01
#define BS_KEY     0x02
#define BS_MOUSE   0x03
#define BS_ACK     0x04
/* Down (Pi -> Mac) */
#define BS_RECT    0x81
#define BS_CURSOR  0x82
#define BS_BEEP    0x83
#define BS_AUDIO   0x84
#define BS_FLOPPY  0x85
#define BS_BYE     0x8F

#define BS_ENC_RAW      0
#define BS_ENC_PACKBITS 1

typedef struct {
    char           magic[2];   /* 'B','S' */
    unsigned char  version;
    unsigned char  flags;
    unsigned short seq;
    unsigned short count;
    unsigned long  length;     /* bytes after the header */
} BSHeader;

typedef struct {
    unsigned char  type;
    unsigned char  reserved;
    unsigned short length;     /* payload bytes; record is padded to even */
} BSRecord;

/* Find the brain on the SCSI bus. Returns its ID (0-6) or -1. */
short LinkFind(void);

/* SEND an up-packet of `len` bytes. */
OSErr LinkSend(short id, Ptr packet, long len);

/* RECEIVE a down-packet into `buf` (capacity `cap`). On success *len is the
   whole packet size including the header. */
OSErr LinkReceive(short id, Ptr buf, long cap, long *len);

#endif
