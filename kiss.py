"""Minimal KISS framing (encode + incremental decode) for talking to a
Bluetooth SPP TNC over a plain RFCOMM socket. No TNC command frames
(port/type byte is always 0 = data on port 0), which is all a
Mobilinkd-style TNC needs.
"""

FEND = 0xC0
FESC = 0xDB
TFEND = 0xDC
TFESC = 0xDD


def kiss_encode(payload, port=0):
    body = bytearray([port << 4])
    for b in payload:
        if b == FEND:
            body += bytes([FESC, TFEND])
        elif b == FESC:
            body += bytes([FESC, TFESC])
        else:
            body.append(b)
    return bytes([FEND, *body, FEND])


class KissDecoder:
    """Incrementally decodes a byte stream into complete KISS frames.
    Each returned frame still has its leading port/command byte -- the
    caller strips it (frame[1:]) to get the raw AX.25 payload."""

    def __init__(self):
        self._buf = bytearray()
        self._in_frame = False
        self._escaped = False

    def feed(self, data):
        frames = []
        for b in data:
            if b == FEND:
                if self._in_frame and self._buf:
                    frames.append(bytes(self._buf))
                self._buf = bytearray()
                self._in_frame = True
                self._escaped = False
                continue
            if not self._in_frame:
                continue  # noise between frames
            if self._escaped:
                if b == TFEND:
                    self._buf.append(FEND)
                elif b == TFESC:
                    self._buf.append(FESC)
                else:
                    self._buf.append(b)  # malformed escape; pass through
                self._escaped = False
            elif b == FESC:
                self._escaped = True
            else:
                self._buf.append(b)
        return frames
