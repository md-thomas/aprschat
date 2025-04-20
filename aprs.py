import socket
import time
import threading
import uuid
import logging

# Set up logging configuration
logging.basicConfig(
    filename='aprs_messages.log',  # Log messages to a file
    level=logging.INFO,  # Log messages with level INFO and above
    format='%(asctime)s - %(levelname)s - %(message)s'  # Log format
)

class APRSClient:
    def __init__(self, callsign, password, server='rotate.aprs2.net', port=14580):
        self.callsign = callsign
        self.password = password
        self.server = server
        self.port = port
        self.socket = None
        self.running = False
        self.received_messages = []
        self.processed_message_ids = set()

    def connect(self):
        """Establishes a connection to the APRS-IS server."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.server, self.port))
        login_message = f"user {self.callsign} pass {self.password} vers FlaskAPRSClient 1.0\r\n"
        self.socket.sendall(login_message.encode())
        time.sleep(2)  # Wait for server response

    def send_message(self, to_callsign, message):
        if not self.socket:
            raise ConnectionError("Not connected to APRS-IS server.")
    
        # Pad recipient to 9 characters (APRS spec)
        to_callsign_padded = to_callsign.upper().ljust(9)

        # if len(message) > 67:
        #     print(f"[WARNING] Message too long. Trimming to 67 characters.")
        #     message = message[:67]
            
        aprs_packet = f"{self.callsign}>APRS,TCPIP*::{to_callsign_padded}:{message}\r\n"
        
        # log messages being sent
        logging.info(f"Sent message to {to_callsign}: {message}")

        print("Sending APRS packet:", aprs_packet.strip())
        self.socket.sendall(aprs_packet.encode())

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
                        if f"::{self.callsign.upper()}" in line.upper():
                            msg = self.parse_message(line)
                            if msg:
                                msgid = msg.get("msgid")
                                if msgid and msgid not in self.processed_message_ids:
                                    self.received_messages.append(msg)
                                    self.processed_message_ids.add(msgid)
                                    logging.info(f"Received message from {msg['from']}: {msg['msg']} (ID: {msgid})")
                                    print(f"[DEDUP] Stored new message: {msg}")
                                    self.send_ack(msgid)
                                else:
                                    print(f"[DEDUP] Skipped duplicate message with ID: {msgid}")
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
