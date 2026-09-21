"""APRS packet building/parsing shared between transports (APRS-IS text
frames in aprs.py, AX.25 UI frames in bluetooth_tnc.py).

Both transports carry the same "info field" format defined by the APRS
spec -- an APRS-IS TNC2 line is literally `SRC>DEST,PATH:` followed by
the same info field an AX.25 UI frame carries as its payload. Keeping
the info-field building/parsing here means a message or position looks
byte-for-byte identical on the air as it does over APRS-IS.
"""

import time


def format_lat(lat):
    hemi = 'N' if lat >= 0 else 'S'
    lat = abs(lat)
    degrees = int(lat)
    minutes = (lat - degrees) * 60
    return f"{degrees:02d}{minutes:05.2f}{hemi}"


def format_lon(lon):
    hemi = 'E' if lon >= 0 else 'W'
    lon = abs(lon)
    degrees = int(lon)
    minutes = (lon - degrees) * 60
    return f"{degrees:03d}{minutes:05.2f}{hemi}"


def parse_lat(lat_str):
    try:
        degrees = int(lat_str[0:2])
        minutes = float(lat_str[2:7])
        value = degrees + minutes / 60
        return -value if lat_str[7] == 'S' else value
    except (ValueError, IndexError):
        return None


def parse_lon(lon_str):
    try:
        degrees = int(lon_str[0:3])
        minutes = float(lon_str[3:8])
        value = degrees + minutes / 60
        return -value if lon_str[8] == 'W' else value
    except (ValueError, IndexError):
        return None


def message_info_field(to_callsign, message, msg_num):
    """Info field for an APRS message packet (starts with ':', the
    message packet-type indicator)."""
    to_callsign_padded = to_callsign.upper().ljust(9)
    return f":{to_callsign_padded}:{message}{{{msg_num}"


def position_info_field(lat, lon, comment='', symbol_table='/', symbol_code='-'):
    """Info field for an uncompressed APRS position report (no timestamp)."""
    lat_str = format_lat(lat)
    lon_str = format_lon(lon)
    return f"!{lat_str}{symbol_table}{lon_str}{symbol_code}{comment}"


def parse_message(packet, my_callsign):
    """Parse a TNC2-format line ('SRC>DEST,PATH::TOCALL  :msg{id') into
    a message dict, or None if it isn't an APRS message packet."""
    try:
        parts = packet.split("::")
        if len(parts) > 1:
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

                return {
                    "from": from_callsign,
                    "msg": msg,
                    "msgid": msgid,
                    "time": time.strftime('%Y-%m-%d %H:%M:%S'),
                }
    except Exception as e:
        print(f"Error parsing message: {e}")
    return None


def parse_position(packet):
    """Parse an uncompressed APRS position report (!/=/@//) from a raw
    TNC2-format line, or None."""
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

        lat_str, symbol_table, lon_str, symbol_code = body[0:8], body[8], body[9:18], body[18]
        if lat_str[-1] not in 'NS' or lon_str[-1] not in 'EW':
            return None  # not the plain uncompressed format we support

        lat = parse_lat(lat_str)
        lon = parse_lon(lon_str)
        if lat is None or lon is None:
            return None

        return {
            'from': from_callsign,
            'lat': lat,
            'lon': lon,
            'comment': body[19:].strip(),
            'symbol_table': symbol_table,
            'symbol_code': symbol_code,
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
    except Exception as e:
        print(f"Error parsing position: {e}")
        return None
