"""RFCOMM connect helper for a classic-Bluetooth (SPP) KISS TNC, e.g. a
Mobilinkd TNC3/TNC4. The TNC speaks real KISS framing directly on the
link -- no application handshake to probe, just a serial socket. The
only unknown is which RFCOMM channel the SPP service is on (TNC3
defaults to 6, TNC4 to 1), so this asks the device's own SDP record
first and falls back to trying both known defaults.
"""

import re
import socket
import subprocess

KNOWN_CHANNELS = (1, 6)  # TNC4 default, then TNC3 default
CONNECT_TIMEOUT_SECONDS = 5.0
SDP_TIMEOUT_SECONDS = 10.0


def discover_channel(addr):
    """Ask the device's SDP record for its Serial Port channel via
    sdptool (part of bluez-utils). Returns None if sdptool isn't
    installed, times out, or the device has no SP record to query."""
    try:
        result = subprocess.run(
            ["sdptool", "search", "--bdaddr", addr, "SP"],
            capture_output=True, text=True, timeout=SDP_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Channel:\s*(\d+)", result.stdout)
    return int(match.group(1)) if match else None


def connect_rfcomm(addr, channel=None):
    """Open a connected RFCOMM socket to the TNC. Tries `channel` if
    given, otherwise the SDP-reported channel, otherwise both known
    defaults in turn."""
    if channel is not None:
        channels = [channel]
    else:
        sdp_channel = discover_channel(addr)
        channels = [sdp_channel] if sdp_channel is not None else list(KNOWN_CHANNELS)

    last_error = None
    for ch in channels:
        s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        s.settimeout(CONNECT_TIMEOUT_SECONDS)
        try:
            s.connect((addr, ch))
            s.settimeout(None)
            return s
        except OSError as e:
            last_error = e
            s.close()

    raise ConnectionError(
        f"Couldn't open an RFCOMM connection to {addr} on channel(s) "
        f"{channels}: {last_error}. Is the TNC on, in range, and paired?"
    ) from last_error
