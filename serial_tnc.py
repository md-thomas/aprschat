"""APRS over a USB-connected KISS TNC, speaking raw AX.25 UI frames over
a serial port instead of Bluetooth RFCOMM. Protocol logic lives in
kiss_tnc.KissTNCClient; this just supplies the serial transport and
port discovery.
"""

import serial
import serial.tools.list_ports

from kiss_tnc import KissTNCClient

DEFAULT_BAUDRATE = 9600
READ_TIMEOUT_SECONDS = 1  # short so disconnect()/a dead port are noticed promptly


def list_serial_ports():
    """Likely USB serial TNCs, via pyserial's own device enumeration.
    Restricted to actual USB devices (vid is set) so this doesn't flood
    the picker with a platform's built-in legacy /dev/ttyS* UARTs, which
    are never a USB TNC."""
    return [
        {'port': p.device, 'description': p.description}
        for p in serial.tools.list_ports.comports()
        if p.vid is not None
    ]


class SerialTNCClient(KissTNCClient):
    transport_name = "USB TNC"

    def __init__(self, callsign, port='', baudrate=DEFAULT_BAUDRATE, digipath=None):
        super().__init__(callsign, digipath)
        self.port = port
        self.baudrate = baudrate

    def _open(self):
        if not self.port:
            raise ConnectionError("No USB device selected.")
        return serial.Serial(self.port, self.baudrate, timeout=READ_TIMEOUT_SECONDS)

    def _read(self, handle):
        # A read timeout returns b'' -- that's "nothing yet", not closed.
        # A real failure (e.g. the device was unplugged) raises instead.
        return handle.read(4096)

    def _write(self, handle, data):
        handle.write(data)

    def _close(self, handle):
        handle.close()
