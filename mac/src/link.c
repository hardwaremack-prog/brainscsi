/* BrainSCSI link — SCSI Manager calls (works on every Mac from the Plus up,
   System 6 and 7). */
#include <SCSI.h>
#include <Memory.h>
#include <string.h>

#include "link.h"

/* Blind transfers are much faster on the SE's NCR 5380, but they assume the
   target always keeps up. PiSCSI does; set to 0 if you ever see hangs. */
#ifndef BS_USE_BLIND
#define BS_USE_BLIND 1
#endif

#define CMD_INQUIRY 0x12
#define CMD_RECEIVE 0x08
#define CMD_SEND    0x0A
#define COMPLETE_TICKS 300   /* 5 seconds */

static OSErr Start(short id, unsigned char *cdb)
{
    OSErr err = SCSIGet();
    if (err) return err;
    err = SCSISelect(id);
    if (err) return err;
    err = SCSICmd((Ptr)cdb, 6);
    if (err) {
        short stat, msg;
        SCSIComplete(&stat, &msg, 60);   /* tidy the bus up */
    }
    return err;
}

static OSErr Finish(void)
{
    short stat = 0, msg = 0;
    OSErr err = SCSIComplete(&stat, &msg, COMPLETE_TICKS);
    if (err) return err;
    return (stat & 0x1E) ? -1 : noErr;   /* any status but GOOD is an error */
}

static OSErr Read(Ptr dst, long n, Boolean blind)
{
    SCSIInstr tib[2];
    tib[0].scOpcode = scInc;  tib[0].scParam1 = (long)dst; tib[0].scParam2 = n;
    tib[1].scOpcode = scStop; tib[1].scParam1 = 0;         tib[1].scParam2 = 0;
    return blind ? SCSIRBlind((Ptr)tib) : SCSIRead((Ptr)tib);
}

static OSErr Write(Ptr src, long n, Boolean blind)
{
    SCSIInstr tib[2];
    tib[0].scOpcode = scInc;  tib[0].scParam1 = (long)src; tib[0].scParam2 = n;
    tib[1].scOpcode = scStop; tib[1].scParam1 = 0;         tib[1].scParam2 = 0;
    return blind ? SCSIWBlind((Ptr)tib) : SCSIWrite((Ptr)tib);
}

static void Length24(unsigned char *cdb, long n)
{
    cdb[2] = (n >> 16) & 0xFF;
    cdb[3] = (n >> 8) & 0xFF;
    cdb[4] = n & 0xFF;
}

short LinkFind(void)
{
    short id;
    for (id = 0; id <= 6; id++) {
        unsigned char cdb[6] = { CMD_INQUIRY, 0, 0, 0, 36, 0 };
        unsigned char inq[36];
        OSErr err;
        memset(inq, 0, sizeof inq);
        if (Start(id, cdb) != noErr) {
            /* Nobody home at this ID. */
            continue;
        }
        err = Read((Ptr)inq, 36, false);
        if (Finish() == noErr && err == noErr &&
            (inq[0] & 0x1F) == 0x03 && memcmp(inq + 8, "BRAIN   ", 8) == 0)
            return id;
    }
    return -1;
}

OSErr LinkSend(short id, Ptr packet, long len)
{
    unsigned char cdb[6] = { CMD_SEND, 0, 0, 0, 0, 0 };
    OSErr err, err2;
    Length24(cdb, len);
    err = Start(id, cdb);
    if (err) return err;
    err = Write(packet, len, BS_USE_BLIND && len >= 512);
    err2 = Finish();
    return err ? err : err2;
}

OSErr LinkReceive(short id, Ptr buf, long cap, long *len)
{
    unsigned char cdb[6] = { CMD_RECEIVE, 0, 0, 0, 0, 0 };
    BSHeader *h = (BSHeader *)buf;
    OSErr err, err2;

    *len = 0;
    Length24(cdb, cap);
    err = Start(id, cdb);
    if (err) return err;

    /* Step 1: the 12-byte header tells us exactly how much follows. */
    err = Read(buf, BS_HEADER_SIZE, false);
    if (!err && (h->magic[0] != 'B' || h->magic[1] != 'S' ||
                 h->version != BS_VERSION ||
                 h->length > (unsigned long)(cap - BS_HEADER_SIZE)))
        err = -2;

    /* Step 2: the body, in the same command. */
    if (!err && h->length > 0)
        err = Read(buf + BS_HEADER_SIZE, h->length, BS_USE_BLIND && h->length >= 512);

    err2 = Finish();
    if (err) return err;
    if (err2) return err2;
    *len = BS_HEADER_SIZE + h->length;
    return noErr;
}
