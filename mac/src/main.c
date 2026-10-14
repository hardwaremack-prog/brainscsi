/* BrainSCSI — Mac SE client.

   Turns the Mac into a terminal for a Raspberry Pi on the SCSI port:
   reads the keyboard and mouse, sends them to the Pi, and draws the screen
   rectangles the Pi sends back straight into screen memory.

   Quit: hold Command + Option + Shift and press Q.

   Builds with Retro68 (68k). See mac/README.md. */
#include <Quickdraw.h>
#include <Fonts.h>
#include <Windows.h>
#include <Menus.h>
#include <TextEdit.h>
#include <Dialogs.h>
#include <Events.h>
#include <Memory.h>
#include <OSUtils.h>
#include <ToolUtils.h>
#include <string.h>

#include "link.h"

#define DOWN_BUF   32768L   /* receive buffer; the Pi never sends more */
#define UP_BUF     1024
#define MAX_ERRORS 5

#define KEY_CMD    55
#define KEY_SHIFT  56
#define KEY_OPTION 58
#define KEY_Q      12

static Ptr            gDown;
static unsigned char  gUp[UP_BUF];
static long           gUpLen;
static unsigned short gUpCount;
static unsigned short gSeq;
static unsigned short gLastDownSeq;
static Cursor         gCursor;
static Boolean        gQuit;

/* ---- building up-packets ------------------------------------------------ */

static void UpBegin(void)
{
    gUpLen = BS_HEADER_SIZE;
    gUpCount = 0;
}

static void UpRecord(unsigned char type, const void *payload, unsigned short n)
{
    BSRecord *r;
    long need = sizeof(BSRecord) + n + (n & 1);
    if (gUpLen + need > UP_BUF) return;          /* drop if somehow full */
    r = (BSRecord *)(gUp + gUpLen);
    r->type = type;
    r->reserved = 0;
    r->length = n;
    BlockMove((Ptr)payload, (Ptr)(r + 1), n);
    if (n & 1) gUp[gUpLen + sizeof(BSRecord) + n] = 0;
    gUpLen += need;
    gUpCount++;
}

static void UpFinish(void)
{
    BSHeader *h = (BSHeader *)gUp;
    h->magic[0] = 'B';
    h->magic[1] = 'S';
    h->version = BS_VERSION;
    h->flags = 0;
    h->seq = ++gSeq;
    h->count = gUpCount;
    h->length = gUpLen - BS_HEADER_SIZE;
}

static void AddHello(void)
{
    unsigned short p[6];
    p[0] = BS_VERSION;
    p[1] = qd.screenBits.bounds.right - qd.screenBits.bounds.left;
    p[2] = qd.screenBits.bounds.bottom - qd.screenBits.bounds.top;
    p[3] = qd.screenBits.rowBytes & 0x3FFF;
    p[4] = 0;                     /* machine type: not reported yet */
    p[5] = 0;                     /* features: no sound/floppy in v1 client */
    UpRecord(BS_HELLO, p, sizeof p);
}

static void AddKey(unsigned char code, Boolean down)
{
    unsigned char p[4];
    p[0] = code;
    p[1] = down ? 1 : 0;
    p[2] = p[3] = 0;
    UpRecord(BS_KEY, p, 4);
}

/* ---- reading the keyboard and mouse ------------------------------------- */

static unsigned char gPrevKeys[16];

static Boolean KeyIsDown(const unsigned char *km, short k)
{
    return (km[k >> 3] >> (k & 7)) & 1;
}

static void GatherInput(void)
{
    KeyMap         now;
    unsigned char *km = (unsigned char *)now;
    EventRecord    ev;
    short          k;
    static Point   lastPt = { -1, -1 };
    static Boolean lastBtn = false;
    Point          pt;
    Boolean        btn;

    GetKeys(now);

    /* Every key that changed since last time, modifiers included. */
    for (k = 0; k < 128; k++) {
        Boolean was = KeyIsDown(gPrevKeys, k), is = KeyIsDown(km, k);
        if (was != is) AddKey((unsigned char)k, is);
    }

    /* Quick taps that went down and up between two polls still show up as
       keyDown events — send those as a down/up pair. */
    while (GetNextEvent(keyDownMask, &ev)) {
        k = (ev.message & keyCodeMask) >> 8;
        if (!KeyIsDown(km, k) && !KeyIsDown(gPrevKeys, k)) {
            AddKey((unsigned char)k, true);
            AddKey((unsigned char)k, false);
        }
    }
    FlushEvents(everyEvent, 0);   /* we read the hardware; don't let events pile up */

    if (KeyIsDown(km, KEY_CMD) && KeyIsDown(km, KEY_OPTION) &&
        KeyIsDown(km, KEY_SHIFT) && KeyIsDown(km, KEY_Q))
        gQuit = true;

    memcpy(gPrevKeys, km, 16);

    GetMouse(&pt);               /* our port covers the screen: global coords */
    btn = Button();
    if (pt.h != lastPt.h || pt.v != lastPt.v || btn != lastBtn) {
        short p[3];
        p[0] = pt.h;
        p[1] = pt.v;
        p[2] = btn ? 0x0100 : 0;  /* u8 buttons, u8 pad */
        UpRecord(BS_MOUSE, p, 6);
        lastPt = pt;
        lastBtn = btn;
    }

    UpRecord(BS_ACK, &gLastDownSeq, 2);
}

/* ---- drawing what the Pi sends ------------------------------------------ */

static void DrawRect(unsigned char *p, unsigned short len)
{
    unsigned short *f = (unsigned short *)p;
    short   x = f[0], y = f[1], w = f[2], h = f[3];
    unsigned char enc = p[8];
    Ptr     src = (Ptr)(p + 10);
    short   rb = w >> 3;
    short   screenRB = qd.screenBits.rowBytes & 0x3FFF;
    Ptr     row = qd.screenBits.baseAddr + (long)y * screenRB + (x >> 3);
    Rect    r;
    Point   zero = { 0, 0 };
    short   i;

    if (x + w > qd.screenBits.bounds.right || y + h > qd.screenBits.bounds.bottom)
        return;                   /* never write outside the screen */

    SetRect(&r, x, y, x + w, y + h);
    ShieldCursor(&r, zero);       /* keep the cursor from smearing */

    if (enc == BS_ENC_RAW) {
        if ((long)rb * h <= (long)len - 10)
            for (i = 0; i < h; i++, row += screenRB, src += rb)
                BlockMove(src, row, rb);
    } else if (enc == BS_ENC_PACKBITS) {
        for (i = 0; i < h; i++, row += screenRB) {
            Ptr dst = row;
            UnpackBits(&src, &dst, rb);   /* the Toolbox does the work */
        }
    }

    ShowCursor();
}

static void ApplyDown(long len)
{
    BSHeader      *h = (BSHeader *)gDown;
    unsigned char *p = (unsigned char *)gDown + BS_HEADER_SIZE;
    unsigned char *end = (unsigned char *)gDown + len;
    unsigned short i;

    for (i = 0; i < h->count && p + sizeof(BSRecord) <= end; i++) {
        BSRecord      *r = (BSRecord *)p;
        unsigned char *body = (unsigned char *)(r + 1);
        if (body + r->length > end) break;

        switch (r->type) {
        case BS_RECT:
            if (r->length >= 10) DrawRect(body, r->length);
            break;
        case BS_CURSOR:
            if (r->length >= sizeof(Cursor)) {
                BlockMove((Ptr)body, (Ptr)&gCursor, sizeof(Cursor));
                SetCursor(&gCursor);
            }
            break;
        case BS_BEEP:
            SysBeep(r->length >= 2 ? *(short *)body : 10);
            break;
        case BS_BYE:
            gQuit = true;
            break;
        default:
            break;                /* AUDIO / FLOPPY: later versions */
        }
        p = body + r->length + (r->length & 1);
    }
    gLastDownSeq = h->seq;
}

/* ---- startup ------------------------------------------------------------ */

static void Message(const char *text)
{
    Rect r;
    SetRect(&r, 96, 140, 416, 200);
    EraseRect(&r);
    FrameRect(&r);
    MoveTo(r.left + 12, r.top + 24);
    DrawText(text, 0, strlen(text));
    MoveTo(r.left + 12, r.top + 44);
    DrawText("Click to continue.", 0, 18);
    while (!Button()) SystemTask();
    while (Button()) SystemTask();
}

int main(void)
{
    GrafPort port;
    short    id, errors = 0;
    Boolean  needHello = true;

    InitGraf(&qd.thePort);
    InitFonts();
    InitWindows();
    InitMenus();
    TEInit();
    InitDialogs(NULL);
    InitCursor();
    FlushEvents(everyEvent, 0);

    OpenPort(&port);              /* a port over the whole screen */

    gDown = NewPtr(DOWN_BUF);
    if (!gDown) {
        Message("Not enough memory for BrainSCSI (needs 32K).");
        return 0;
    }

    id = LinkFind();
    if (id < 0) {
        Message("No BrainSCSI found on the SCSI bus.");
        return 0;
    }

    while (!gQuit) {
        long  len;
        OSErr err;

        UpBegin();
        if (needHello) {
            AddHello();
            needHello = false;
        }
        GatherInput();
        UpFinish();

        err = LinkSend(id, (Ptr)gUp, gUpLen);
        if (!err) {
            /* Keep pulling while the Pi says there's more for this frame. */
            do {
                err = LinkReceive(id, gDown, DOWN_BUF, &len);
                if (!err) ApplyDown(len);
            } while (!err && (((BSHeader *)gDown)->flags & BS_FLAG_MORE) && !gQuit);
        }

        if (err) {
            if (++errors >= MAX_ERRORS) {
                Message("Lost the BrainSCSI link.");
                break;
            }
            needHello = true;     /* start fresh: Pi will resend the screen */
        } else {
            errors = 0;
        }
        SystemTask();
    }

    InitCursor();
    /* Returning to the Finder redraws the desktop over our pixels. */
    return 0;
}
