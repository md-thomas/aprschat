"""Minimal AX.25 UI-frame encode/decode for APRS-over-RF.

Only what APRS actually needs: unnumbered information (UI) frames with
PID 0xF0 (no layer 3) -- no connected-mode state machine, no mod-128
extended sequence numbers. Adapted from the address field encoding
rules in AX.25 v2.2 section 3.12.

Frames here are raw AX.25 bytes (destination/source/digipeater
addresses + control + PID + info) with no KISS framing -- see kiss.py
for that layer.
"""

UI_CONTROL = 0x03
PID_NO_LAYER3 = 0xF0

MAX_DIGIPEATERS = 8


def _split_callsign(callsign):
    if '-' in callsign:
        call, ssid = callsign.split('-', 1)
        return call, int(ssid)
    return callsign, 0


def _encode_address(callsign, ssid, last, command_or_repeated):
    cs = callsign.upper()[:6].ljust(6)
    raw = bytearray((ord(c) << 1) for c in cs)
    # Reserved bits (6-5) are conventionally sent as 1; bit 0 is the
    # extension bit (1 marks the last address field).
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1) | (1 if last else 0)
    if command_or_repeated:
        ssid_byte |= 0x80
    raw.append(ssid_byte)
    return bytes(raw)


def encode_ui_frame(source, dest, digipeaters, info):
    """Build a raw AX.25 UI frame: DEST, SOURCE, [digipeaters...],
    control=0x03 (UI), pid=0xF0 (no layer 3), then `info` (bytes)."""
    addrs = [_split_callsign(dest), _split_callsign(source)]
    addrs += [_split_callsign(d) for d in digipeaters[:MAX_DIGIPEATERS]]

    out = bytearray()
    for i, (call, ssid) in enumerate(addrs):
        last = (i == len(addrs) - 1)
        # Command bit set on the destination address (index 0), per the
        # AX.25 command/response convention for an unconnected UI frame.
        flag = (i == 0)
        out += _encode_address(call, ssid, last, flag)

    out.append(UI_CONTROL)
    out.append(PID_NO_LAYER3)
    out += info
    return bytes(out)


def _decode_address(raw):
    callsign = "".join(chr(b >> 1) for b in raw[:6]).rstrip(" ")
    ssid_byte = raw[6]
    ssid = (ssid_byte >> 1) & 0x0F
    flag = bool(ssid_byte & 0x80)  # C bit on dest/source, H bit on a digipeater
    last = bool(ssid_byte & 0x01)
    return callsign, ssid, flag, last


def decode_frame(raw):
    """Decode one raw AX.25 frame. Returns a dict with 'from', 'to',
    'path' (comma-joined digipeaters, '*' marking a repeated one), and
    'payload' (bytes) -- or None if `raw` isn't a well-formed UI frame
    carrying APRS's PID (no layer 3)."""
    if len(raw) < 15:  # dest(7) + source(7) + control(1), minimum
        return None

    pos = 0
    addrs = []
    while True:
        if pos + 7 > len(raw):
            return None
        callsign, ssid, flag, last = _decode_address(raw[pos:pos + 7])
        addrs.append((callsign, ssid, flag))
        pos += 7
        if last:
            break
        if len(addrs) >= 2 + MAX_DIGIPEATERS:
            return None

    if len(addrs) < 2 or pos >= len(raw):
        return None
    dest, source, *digis = addrs

    control = raw[pos]
    pos += 1
    if control & ~0x10 != UI_CONTROL:
        return None  # not a UI frame

    if pos >= len(raw):
        return None
    pid = raw[pos]
    pos += 1
    if pid != PID_NO_LAYER3:
        return None

    def fmt_call(call, ssid):
        return f"{call}-{ssid}" if ssid else call

    def fmt_digi(addr):
        call, ssid, repeated = addr
        cs = fmt_call(call, ssid)
        return f"{cs}*" if repeated else cs

    return {
        # dest/source's flag bit is the command/response (C) bit, not
        # "repeated" -- that only applies to digipeaters (their H bit).
        'from': fmt_call(source[0], source[1]),
        'to': fmt_call(dest[0], dest[1]),
        'path': ",".join(fmt_digi(d) for d in digis),
        'payload': raw[pos:],
    }
