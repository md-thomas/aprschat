import socket
import time
import threading
import uuid
import logging
import random
import string

import aprs_packet


# Set up logging configuration
logging.basicConfig(
    filename='aprs_messages.log',  # Log messages to a file
    level=logging.INFO,  # Log messages with level INFO and above
    format='%(asctime)s - %(levelname)s - %(message)s'  # Log format
)

class APRSClient:
    # def __init__(self, callsign, password, server='rotate.aprs2.net', port=14580):
    def __init__(self, callsign, password, server='noam.aprs2.net', port=14580):
        self.callsign = callsign
        self.password = password
        self.server = server
        self.port = port
        self.socket = None
        self.running = False
        self.received_messages = []
        self.processed_message_ids = set()
        self.positions = {}
        self.watch_list = {callsign.upper()}
        self.counter = 0

    def get_next_id(self):
        self.counter = (self.counter + 1) % 100000
        return f"{self.counter:03}"

    def connect(self, watch_callsigns=None):
        """Establishes a connection to the APRS-IS server."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.server, self.port))
        login_message = f"user {self.callsign} pass {self.password} vers FlaskAPRSClient 1.0\r\n"
        self.socket.sendall(login_message.encode())
        time.sleep(1)  # Wait for server response

        self.set_filter(watch_callsigns or [])

    def set_filter(self, watch_callsigns):
        """(Re)send the APRS-IS server-side filter to include the given callsigns."""
        self.watch_list = {self.callsign.upper()} | {c.strip().upper() for c in watch_callsigns if c.strip()}
        callsigns_csv = ",".join(sorted(self.watch_list))

        # Traffic (messages, positions, etc.) from these callsigns + weather alerts
        filter_command = f"# filter t/m p/{callsigns_csv} t/w\r\n"
        if self.socket:
            self.socket.sendall(filter_command.encode())

    def send_message(self, to_callsign, message):
        if not self.socket:
            raise ConnectionError("Not connected to APRS-IS server.")

        msg_num = self.get_next_id()
        info = aprs_packet.message_info_field(to_callsign, message, msg_num)
        packet = f"{self.callsign}>APRS,TCPIP*:{info}\r\n"

        # log messages being sent
        logging.info(f"Sent message to {to_callsign}: {message}")

        print("Sending APRS packet:", packet.strip())
        self.socket.sendall(packet.encode())

    def send_position(self, lat, lon, comment='', symbol_table='/', symbol_code='-'):
        if not self.socket:
            raise ConnectionError("Not connected to APRS-IS server.")

        info = aprs_packet.position_info_field(lat, lon, comment, symbol_table, symbol_code)
        packet = f"{self.callsign}>APRS,TCPIP*:{info}\r\n"

        logging.info(f"Sent position: {lat},{lon} {comment}")
        print("Sending APRS position packet:", packet.strip())
        self.socket.sendall(packet.encode())

        # Show our own sent position immediately (APRS-IS won't echo it back to us)
        self.positions[self.callsign.upper()] = {
            'from': self.callsign.upper(),
            'lat': lat,
            'lon': lon,
            'comment': comment,
            'symbol_table': symbol_table,
            'symbol_code': symbol_code,
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        }

    def parse_position(self, packet):
        """Parse an uncompressed APRS position report (!/=/@//) from a raw APRS-IS line."""
        return aprs_packet.parse_position(packet)

    def send_ack(self, msgid):
        # Create the acknowledgment message using the message ID.
        ack_message = f"ack{msgid}"  # Format: ack{msgid}
        
        logging.info(f"Sent acknowledgment for message ID: {msgid}")

        # Send the acknowledgment (use the proper method to send it to APRS)
        self.send_message(self.callsign, ack_message)
        print(f"Sent acknowledgment: {ack_message}")

    def listen_for_messages(self):
        def listen():
            self.running = True
            buffer = ""
            while self.running:
                try:
                    data = self.socket.recv(4096).decode(errors='ignore')
                    buffer += data
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        # print(line)
                        if f"::{self.callsign.upper()}" in line.upper():
                            msg = self.parse_message(line)
                            if msg:
                                msgid = msg.get("msgid")
                                if msgid and msgid not in self.processed_message_ids:
                                    self.received_messages.append(msg)
                                    self.processed_message_ids.add(msgid)
                                    logging.info(f"Received message from {msg['from']}: {msg['msg']} (ID: {msgid})")
                                    print(f"[DEDUP] Stored new message: {msg}")
                                    # self.send_ack(msgid)
                                else:
                                    print(f"[DEDUP] Skipped duplicate message with ID: {msgid}")
                        else:
                            pos = self.parse_position(line)
                            if pos and pos['from'] in self.watch_list:
                                self.positions[pos['from']] = pos
                                logging.info(f"Position from {pos['from']}: {pos['lat']},{pos['lon']}")
                                print(f"[POSITION] {pos}")
                except Exception as e:
                    print("Error receiving APRS:", e)
                    self.running = False
        thread = threading.Thread(target=listen, daemon=True)
        thread.start()

    def parse_message(self, packet):
        return aprs_packet.parse_message(packet, self.callsign)

    def close(self):
        """Closes the connection to the APRS-IS server."""
        if self.socket:
            self.socket.close()
            self.socket = None
