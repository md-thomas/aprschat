import socket
import time
import threading
import uuid
import logging
import random
import string


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
    
        # Pad recipient to 9 characters (APRS spec)
        to_callsign_padded = to_callsign.upper().ljust(9)

        # if len(message) > 67:
        #     print(f"[WARNING] Message too long. Trimming to 67 characters.")
        #     message = message[:67]
        
        msg_num = self.get_next_id()
        aprs_packet = f"{self.callsign}>APRS,TCPIP*::{to_callsign_padded}:{message}{{{msg_num}\r\n"
        
        # log messages being sent
        logging.info(f"Sent message to {to_callsign}: {message}")

        print("Sending APRS packet:", aprs_packet.strip())
        self.socket.sendall(aprs_packet.encode())

    @staticmethod
    def _format_lat(lat):
        hemi = 'N' if lat >= 0 else 'S'
        lat = abs(lat)
        degrees = int(lat)
        minutes = (lat - degrees) * 60
        return f"{degrees:02d}{minutes:05.2f}{hemi}"

    @staticmethod
    def _format_lon(lon):
        hemi = 'E' if lon >= 0 else 'W'
        lon = abs(lon)
        degrees = int(lon)
        minutes = (lon - degrees) * 60
        return f"{degrees:03d}{minutes:05.2f}{hemi}"

    @staticmethod
    def _parse_lat(lat_str):
        try:
            degrees = int(lat_str[0:2])
            minutes = float(lat_str[2:7])
            value = degrees + minutes / 60
            return -value if lat_str[7] == 'S' else value
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _parse_lon(lon_str):
        try:
            degrees = int(lon_str[0:3])
            minutes = float(lon_str[3:8])
            value = degrees + minutes / 60
            return -value if lon_str[8] == 'W' else value
        except (ValueError, IndexError):
            return None

    def send_position(self, lat, lon, comment=''):
        if not self.socket:
            raise ConnectionError("Not connected to APRS-IS server.")

        lat_str = self._format_lat(lat)
        lon_str = self._format_lon(lon)
        packet = f"{self.callsign}>APRS,TCPIP*:!{lat_str}/{lon_str}-{comment}\r\n"

        logging.info(f"Sent position: {lat},{lon} {comment}")
        print("Sending APRS position packet:", packet.strip())
        self.socket.sendall(packet.encode())

        # Show our own sent position immediately (APRS-IS won't echo it back to us)
        self.positions[self.callsign.upper()] = {
            'from': self.callsign.upper(),
            'lat': lat,
            'lon': lon,
            'comment': comment,
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        }

    def parse_position(self, packet):
        """Parse an uncompressed APRS position report (!/=/@//) from a raw APRS-IS line."""
        try:
            header, info = packet.split(':', 1)
            if not info or info[0] not in ('!', '=', '/', '@'):
                return None

            from_callsign = header.split('>')[0].strip().upper()
            body = info[1:]
            if info[0] in ('/', '@'):
                body = body[7:]  # skip the DDHHMMz/DDHHMM/ timestamp

            if len(body) < 19:
                return None  # too short to be uncompressed lat/lon (likely Mic-E/compressed)

            lat_str, lon_str = body[0:8], body[9:18]
            if lat_str[-1] not in 'NS' or lon_str[-1] not in 'EW':
                return None  # not the plain uncompressed format we support

            lat = self._parse_lat(lat_str)
            lon = self._parse_lon(lon_str)
            if lat is None or lon is None:
                return None

            return {
                'from': from_callsign,
                'lat': lat,
                'lon': lon,
                'comment': body[19:].strip(),
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            }
        except Exception as e:
            print(f"Error parsing position: {e}")
            return None

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
        try:
            parts = packet.split("::")
            if len(parts) > 1:
                # Get everything before '::' (packet header), then split by '>' to get sender callsign
                raw_header = parts[0].strip()
                from_callsign = raw_header.split(">")[0].strip()
    
                rest = parts[1]
                to_and_msg = rest.split(":", 1)
                if len(to_and_msg) == 2:
                    raw_msg = to_and_msg[1].strip()
                    if "{" in raw_msg:
                        msg, msgid = raw_msg.split("{")
                        msgid = msgid.strip()
                    else:
                        msg = raw_msg
                        msgid = None
                    
                    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                    parsed = {
                        "from": from_callsign,
                        "msg": msg,
                        "msgid": msgid,
                        "time": timestamp
                    }
                    print(f"[DEBUG] {parsed}")
                    return parsed
        except Exception as e:
            print(f"Error parsing message: {e}")
            return None

    def close(self):
        """Closes the connection to the APRS-IS server."""
        if self.socket:
            self.socket.close()
            self.socket = None
