"""APRS over a Bluetooth KISS TNC (e.g. a Mobilinkd TNC3/TNC4), speaking
raw AX.25 UI frames over RFCOMM instead of APRS-IS's TNC2 text over TCP.
Protocol logic lives in kiss_tnc.KissTNCClient; this just supplies the
RFCOMM transport and paired-device discovery.
"""

import re
import subprocess

from kiss_tnc import KissTNCClient
from rfcomm_connect import connect_rfcomm

BLUETOOTHCTL_TIMEOUT_SECONDS = 5.0


def list_paired_devices():
    """Paired Bluetooth devices, via `bluetoothctl devices Paired`.
    Returns [] (not an error) if there's no adapter or bluetoothctl
    isn't installed -- that's just "nothing to pick from"."""
    try:
        result = subprocess.run(
            ["bluetoothctl", "devices", "Paired"],
            capture_output=True, text=True, timeout=BLUETOOTHCTL_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    devices = []
    for line in result.stdout.splitlines():
        match = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)", line.strip())
        if match:
            devices.append({'address': match.group(1), 'name': match.group(2).strip()})
    return devices


class BluetoothTNCClient(KissTNCClient):
    transport_name = "Bluetooth TNC"

    def __init__(self, callsign, address='', channel=None, digipath=None):
        super().__init__(callsign, digipath)
        self.address = address
        self.channel = channel

    def _open(self):
        if not self.address:
            raise ConnectionError("No Bluetooth device selected.")
        return connect_rfcomm(self.address, self.channel)

    def _read(self, handle):
        # Blocking recv: empty bytes here really does mean the peer closed.
        data = handle.recv(4096)
        if not data:
            raise ConnectionError("Bluetooth TNC closed the connection.")
        return data

    def _write(self, handle, data):
        handle.sendall(data)

    def _close(self, handle):
        handle.close()
