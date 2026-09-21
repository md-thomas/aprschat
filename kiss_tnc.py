"""Shared protocol logic for an APRS-over-AX.25 KISS TNC client, whatever
the underlying transport (Bluetooth RFCOMM, USB serial). A subclass only
has to say how to open/read/write/close its transport; this handles
AX.25 framing, dedup against aprs_packet, and the background listener.

Unlike aprs.APRSClient (which connects once at app startup and stays
connected), these are meant to be explicitly connected/disconnected by
the user from the Connection panel -- picking a device is meaningless
until they choose one, and real hardware coming and going shouldn't be
hidden behind silent auto-reconnect fighting a deliberate disconnect.
"""

import logging
import threading
import time

import aprs_packet
import ax25
from kiss import KissDecoder, kiss_encode

DEFAULT_DIGIPATH = ['WIDE1-1', 'WIDE2-1']
IDLE_POLL_SECONDS = 1


class KissTNCClient:
    transport_name = "TNC"

    def __init__(self, callsign, digipath=None):
        self.callsign = callsign
        self.digipath = [d.strip().upper() for d in (digipath or []) if d.strip()] or DEFAULT_DIGIPATH
        self.handle = None
        self.connected = False
        self.received_messages = []
        self.processed_message_ids = set()
        self.positions = {}
        self.watch_list = {callsign.upper()}
        self.counter = 0
        self._decoder = KissDecoder()
        self._send_lock = threading.Lock()
        self._listening = False

    # -- transport hooks: implemented by subclasses --
    def _open(self):
        """Open and return a connected transport handle, or raise."""
        raise NotImplementedError

    def _read(self, handle):
        """Return newly-received bytes, or falsy if none arrived within
        this call (e.g. a read timeout) -- NOT necessarily a closed
        link. Raise to signal the link is actually dead."""
        raise NotImplementedError

    def _write(self, handle, data):
        raise NotImplementedError

    def _close(self, handle):
        raise NotImplementedError

    # -- shared protocol --
    def get_next_id(self):
        self.counter = (self.counter + 1) % 100000
        return f"{self.counter:03}"

    def set_filter(self, watch_callsigns):
        """Kept for interface parity with APRSClient -- there's no
        server-side filter over RF, everything heard is already ours to
        keep or discard locally by watch_list."""
        self.watch_list = {self.callsign.upper()} | {c.strip().upper() for c in watch_callsigns if c.strip()}

    def connect(self, watch_callsigns=None):
        """Open the transport. Raises if it can't be opened."""
        if watch_callsigns:
            self.set_filter(watch_callsigns)
        self.handle = self._open()
        self.connected = True
        self._decoder = KissDecoder()
        self.listen_for_messages()

    def disconnect(self):
        self.connected = False
        handle, self.handle = self.handle, None
        if handle:
            try:
                self._close(handle)
            except Exception:
                pass

    close = disconnect  # alias for parity with APRSClient.close()

    def _send_frame(self, info_field):
        if not self.handle:
            raise ConnectionError(f"Not connected to a {self.transport_name}.")
        frame = ax25.encode_ui_frame(
            self.callsign, 'APRS', self.digipath, info_field.encode('ascii', errors='replace')
        )
        with self._send_lock:
            self._write(self.handle, kiss_encode(frame))

    def send_message(self, to_callsign, message):
        msg_num = self.get_next_id()
        info = aprs_packet.message_info_field(to_callsign, message, msg_num)
        logging.info(f"Sent message to {to_callsign} via {self.transport_name}: {message}")
        self._send_frame(info)

    def send_position(self, lat, lon, comment='', symbol_table='/', symbol_code='-'):
        info = aprs_packet.position_info_field(lat, lon, comment, symbol_table, symbol_code)
        logging.info(f"Sent position via {self.transport_name}: {lat},{lon} {comment}")
        self._send_frame(info)

        # Show our own sent position immediately, same as APRSClient does.
        self.positions[self.callsign.upper()] = {
            'from': self.callsign.upper(),
            'lat': lat,
            'lon': lon,
            'comment': comment,
            'symbol_table': symbol_table,
            'symbol_code': symbol_code,
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        }

    def _handle_ax25_frame(self, raw):
        decoded = ax25.decode_frame(raw)
        if not decoded:
            return
        try:
            payload_text = decoded['payload'].decode('ascii', errors='replace')
        except Exception:
            return

        path = f",{decoded['path']}" if decoded['path'] else ''
        # Reconstruct the same TNC2-format line APRS-IS would have sent,
        # so aprs_packet's parser is shared byte-for-byte with aprs.py.
        line = f"{decoded['from']}>{decoded['to']}{path}:{payload_text}"

        if f"::{self.callsign.upper()}" in line.upper():
            msg = aprs_packet.parse_message(line, self.callsign)
            if msg:
                msgid = msg.get('msgid')
                if msgid and msgid not in self.processed_message_ids:
                    self.received_messages.append(msg)
                    self.processed_message_ids.add(msgid)
                    logging.info(f"Received message from {msg['from']} via {self.transport_name}: {msg['msg']}")
        else:
            pos = aprs_packet.parse_position(line)
            if pos and pos['from'] in self.watch_list:
                self.positions[pos['from']] = pos
                logging.info(f"Position from {pos['from']} via {self.transport_name}: {pos['lat']},{pos['lon']}")

    def listen_for_messages(self):
        """Start the background listener thread, once. Safe to call
        repeatedly (e.g. connect() calls it every time)."""
        if self._listening:
            return
        self._listening = True

        def listen():
            while True:
                handle = self.handle
                if not handle:
                    time.sleep(IDLE_POLL_SECONDS)
                    continue
                try:
                    data = self._read(handle)
                except Exception as e:
                    if self.handle is handle:  # still the active handle; a real drop
                        print(f"Error receiving from {self.transport_name}: {e}")
                        self.connected = False
                        self.handle = None
                        try:
                            self._close(handle)
                        except Exception:
                            pass
                    time.sleep(IDLE_POLL_SECONDS)
                    continue
                if not data:
                    continue
                for frame in self._decoder.feed(data):
                    if len(frame) > 1:
                        self._handle_ax25_frame(frame[1:])  # strip KISS port/cmd byte

        thread = threading.Thread(target=listen, daemon=True)
        thread.start()
