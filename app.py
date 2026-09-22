import argparse
import configparser
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from aprs import APRSClient
from bluetooth_tnc import BluetoothTNCClient, list_paired_devices
from serial_tnc import SerialTNCClient, list_serial_ports
from uvpro_tnc import UvProTNCClient
import version

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key='the_secret_key')
app.mount('/static', StaticFiles(directory='static'), name='static')

templates = Jinja2Templates(directory='templates')

# Replace with your actual callsign and password
config = configparser.ConfigParser()
config.read('aprschat.config')
CALLSIGN = config['settings']['callsign']
PASSCODE = config['settings']['passcode']
CONFIG_RADIUS_NM = int(config.get('settings', 'radius_nm', fallback='60').strip() or 60)
CONFIG_RADIUS_FILTER_ENABLED = config.getboolean('settings', 'radius_filter_enabled', fallback=True)

# Bluetooth KISS TNC (e.g. Mobilinkd TNC3/TNC4) and USB KISS TNC settings.
# These are only starting defaults -- the Connection panel lets the user
# pick a live device instead, which then takes precedence (see
# load_connection_state() below), so a stale/missing config entry never
# blocks using whatever's actually plugged in or paired right now.
CONFIG_BT_ADDRESS = config.get('bluetooth', 'address', fallback='').strip()
_bt_channel = config.get('bluetooth', 'channel', fallback='').strip()
BT_CHANNEL = int(_bt_channel) if _bt_channel else None

CONFIG_USB_PORT = config.get('usb', 'port', fallback='').strip()
USB_BAUDRATE = int(config.get('usb', 'baudrate', fallback='9600').strip() or 9600)

# UV-Pro/Benshi-class radio (BTech UV-Pro, Vero VR-N76, ...) -- a different
# Bluetooth protocol from the plain KISS-over-RFCOMM TNCs above, so it gets
# its own address setting and its own client (see uvpro_tnc.py).
CONFIG_UVPRO_ADDRESS = config.get('uvpro', 'address', fallback='').strip()

DIGIPATH = config.get('rf', 'digipath', fallback='WIDE1-1,WIDE2-1').split(',')

# Saved callsigns shown in the sidebar, editable from the web page
CALLSIGNS_FILE = Path('callsigns.json')


def load_callsigns():
    if CALLSIGNS_FILE.exists():
        with open(CALLSIGNS_FILE) as f:
            return sorted(json.load(f))
    return []


def save_callsigns(callsigns):
    with open(CALLSIGNS_FILE, 'w') as f:
        json.dump(callsigns, f, indent=2)


CALLSIGNS = load_callsigns()

# Selected transport + selected device for the Connection panel, all
# four ('network'/APRS-IS, 'bluetooth', 'usb', 'uvpro') fully wired up. The
# device picked from the panel (persisted here) takes precedence over
# aprschat.config's address/port on the next startup, since it reflects
# whatever the user last actually chose.
CONNECTION_MODES = ('network', 'bluetooth', 'usb', 'uvpro')
CONNECTION_FILE = Path('connection.json')


def load_connection_state():
    data = {}
    if CONNECTION_FILE.exists():
        with open(CONNECTION_FILE) as f:
            data = json.load(f)
    mode = data.get('mode', 'network')
    return {
        'mode': mode if mode in CONNECTION_MODES else 'network',
        'bluetooth_address': data.get('bluetooth_address', ''),
        'usb_port': data.get('usb_port', ''),
        'uvpro_address': data.get('uvpro_address', ''),
        'radius_nm': data.get('radius_nm', ''),
        # None (not just falsy), since False is a valid saved value and
        # must not fall back to the config default like '' or 0 would.
        'radius_filter_enabled': data.get('radius_filter_enabled', None),
    }


def save_connection_state():
    with open(CONNECTION_FILE, 'w') as f:
        json.dump({
            'mode': CONNECTION_MODE,
            'bluetooth_address': bt_client.address,
            'usb_port': usb_client.port,
            'uvpro_address': uvpro_client.address,
            'radius_nm': aprs_client.radius_nm,
            'radius_filter_enabled': aprs_client.radius_filter_enabled,
        }, f, indent=2)


_state = load_connection_state()
CONNECTION_MODE = _state['mode']
BT_ADDRESS = _state['bluetooth_address'] or CONFIG_BT_ADDRESS
USB_PORT = _state['usb_port'] or CONFIG_USB_PORT
UVPRO_ADDRESS = _state['uvpro_address'] or CONFIG_UVPRO_ADDRESS
RADIUS_NM = _state['radius_nm'] or CONFIG_RADIUS_NM
RADIUS_FILTER_ENABLED = _state['radius_filter_enabled']
if RADIUS_FILTER_ENABLED is None:
    RADIUS_FILTER_ENABLED = CONFIG_RADIUS_FILTER_ENABLED

aprs_client = APRSClient(CALLSIGN, PASSCODE, radius_nm=RADIUS_NM, radius_filter_enabled=RADIUS_FILTER_ENABLED)
aprs_client.connect(CALLSIGNS)
aprs_client.listen_for_messages()

bt_client = BluetoothTNCClient(CALLSIGN, BT_ADDRESS, BT_CHANNEL, DIGIPATH)
usb_client = SerialTNCClient(CALLSIGN, USB_PORT, USB_BAUDRATE, DIGIPATH)
uvpro_client = UvProTNCClient(CALLSIGN, UVPRO_ADDRESS, DIGIPATH)


def get_active_client():
    """The client that should actually carry traffic for the selected
    Connection mode."""
    if CONNECTION_MODE == 'bluetooth':
        return bt_client
    if CONNECTION_MODE == 'usb':
        return usb_client
    if CONNECTION_MODE == 'uvpro':
        return uvpro_client
    return aprs_client


def is_connected(mode):
    if mode == 'bluetooth':
        return bt_client.connected
    if mode == 'usb':
        return usb_client.connected
    if mode == 'uvpro':
        return uvpro_client.connected
    return bool(aprs_client.socket) and aprs_client.running


# Best-effort: if Bluetooth/USB/UV-Pro was the saved mode with a saved
# device from a previous run, try to reconnect now. If the device isn't
# reachable at startup, the app still comes up -- the Connection panel
# will just show Disconnected until the user hits Connect (or picks a
# different device).
if CONNECTION_MODE == 'bluetooth' and BT_ADDRESS:
    try:
        bt_client.connect(CALLSIGNS)
    except Exception as e:
        print(f"Bluetooth TNC not available at startup: {e}")
elif CONNECTION_MODE == 'usb' and USB_PORT:
    try:
        usb_client.connect(CALLSIGNS)
    except Exception as e:
        print(f"USB TNC not available at startup: {e}")
elif CONNECTION_MODE == 'uvpro' and UVPRO_ADDRESS:
    try:
        uvpro_client.connect(CALLSIGNS)
    except Exception as e:
        print(f"UV-Pro not available at startup: {e}")

# In-memory history (clears when the app restarts)
message_history = []

VERSION = version.__version__


def flash(request: Request, message: str):
    flashes = request.session.get('_flashes', [])
    flashes.append(message)
    request.session['_flashes'] = flashes


def get_flashed_messages(request: Request):
    return request.session.pop('_flashes', [])


def split_message(message: str, limit: int = 67):
    """Split a message into APRS-sized chunks, each prefixed with a (part/total) marker."""
    if len(message) <= limit:
        return [message]

    total_estimate = -(-len(message) // limit)  # ceil division
    marker_len = len(f"({total_estimate}/{total_estimate}) ")
    body_size = max(limit - marker_len, 1)

    bodies = [message[i:i + body_size] for i in range(0, len(message), body_size)]
    total = len(bodies)
    return [f"({i}/{total}) {body}" for i, body in enumerate(bodies, start=1)]


@app.get('/')
async def index(request: Request, to_callsign: str = ''):
    client = get_active_client()
    # Include both sent and received messages in the view
    chat_history = message_history + [
        {'to': client.callsign, 'msg': msg['msg'], 'time': msg['time'], 'direction': 'in'}
        for msg in client.received_messages
    ]

    return templates.TemplateResponse(
        request,
        'index.html',
        {
            'history': chat_history,
            'version': VERSION,
            'callsign': CALLSIGN,
            'to_callsign': to_callsign,
            'callsigns': CALLSIGNS,
            'messages': get_flashed_messages(request),
            'connection_mode': CONNECTION_MODE,
            'connection_connected': is_connected(CONNECTION_MODE),
            'radius_nm': aprs_client.radius_nm,
            'radius_filter_enabled': aprs_client.radius_filter_enabled,
        },
    )


@app.post('/')
async def send_message(request: Request, to_callsign: str = Form(...), message: str = Form(...)):
    recipients = [c.strip().upper() for c in to_callsign.split(',') if c.strip()]
    chunks = split_message(message, 67)

    if len(chunks) > 1:
        flash(request, f"Message was too long and has been split into {len(chunks)} messages...")
        print(f"[WARNING] Message too long. Splitting into {len(chunks)} messages.")
    if len(recipients) > 1:
        flash(request, f"Sending to {len(recipients)} recipients: {', '.join(recipients)}")

    client = get_active_client()
    total_sends = len(recipients) * len(chunks)
    sent = 0
    for recipient in recipients:
        for chunk in chunks:
            sent += 1
            try:
                client.send_message(recipient, chunk)
                message_history.append({
                    'to': recipient,
                    'msg': chunk,
                    'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'direction': 'out'
                })
            except Exception as e:
                message_history.append({
                    'to': recipient,
                    'msg': f"[ERROR] {str(e)}",
                    'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'direction': 'out'
                })
            if total_sends > 1 and sent < total_sends:
                time.sleep(2)  # avoid flooding APRS-IS with rapid-fire packets

    query = urlencode({'to_callsign': to_callsign})
    return RedirectResponse(url=f"/?{query}", status_code=303)


@app.get('/get_messages')
async def get_messages():
    client = get_active_client()
    # Get both sent and received messages
    chat_history = message_history + [
        {
            'from': msg.get('from', 'Unknown'),
            'to': client.callsign,
            'msg': msg['msg'],
            'msgid': msg['msgid'],
            'time': msg['time'],
            'direction': 'in'
        }
        for msg in client.received_messages
    ]

    chat_history.sort(key=lambda x: datetime.strptime(x['time'], '%Y-%m-%d %H:%M:%S'))

    return chat_history


@app.post('/callsigns/add')
async def add_callsign(callsign: str = Form(...)):
    cs = callsign.strip().upper()
    if cs and cs not in CALLSIGNS:
        CALLSIGNS.append(cs)
        CALLSIGNS.sort()
        save_callsigns(CALLSIGNS)
        aprs_client.set_filter(CALLSIGNS)
        bt_client.set_filter(CALLSIGNS)
        usb_client.set_filter(CALLSIGNS)
        uvpro_client.set_filter(CALLSIGNS)
    return RedirectResponse(url='/', status_code=303)


@app.post('/callsigns/remove')
async def remove_callsign(callsign: str = Form(...)):
    cs = callsign.strip().upper()
    if cs in CALLSIGNS:
        CALLSIGNS.remove(cs)
        save_callsigns(CALLSIGNS)
        aprs_client.set_filter(CALLSIGNS)
        bt_client.set_filter(CALLSIGNS)
        usb_client.set_filter(CALLSIGNS)
        uvpro_client.set_filter(CALLSIGNS)
    return RedirectResponse(url='/', status_code=303)


@app.post('/connection/set')
async def set_connection_mode(mode: str = Form(...)):
    global CONNECTION_MODE
    mode = mode.strip().lower()
    if mode in CONNECTION_MODES:
        CONNECTION_MODE = mode
        save_connection_state()
    return RedirectResponse(url='/', status_code=303)


@app.post('/connection/radius')
async def set_radius(radius_nm: int = Form(...)):
    aprs_client.radius_nm = max(1, radius_nm)
    aprs_client.set_filter(CALLSIGNS)  # resend the filter with the new radius
    save_connection_state()
    return RedirectResponse(url='/', status_code=303)


@app.post('/connection/radius/toggle')
async def toggle_radius_filter(enabled: bool = Form(...)):
    aprs_client.radius_filter_enabled = enabled
    aprs_client.set_filter(CALLSIGNS)  # resend the filter in the new mode
    save_connection_state()
    return {'radius_filter_enabled': aprs_client.radius_filter_enabled}


@app.get('/connection/status')
async def connection_status():
    return {
        'mode': CONNECTION_MODE,
        'connected': is_connected(CONNECTION_MODE),
    }


@app.get('/connection/bluetooth/devices')
async def bluetooth_devices():
    return {'devices': list_paired_devices(), 'selected': bt_client.address}


@app.post('/connection/bluetooth/connect')
async def bluetooth_connect(address: str = Form(...)):
    bt_client.disconnect()
    bt_client.address = address.strip()
    save_connection_state()
    try:
        bt_client.connect(CALLSIGNS)
        return {'connected': True}
    except Exception as e:
        return {'connected': False, 'error': str(e)}


@app.post('/connection/bluetooth/disconnect')
async def bluetooth_disconnect():
    bt_client.disconnect()
    return {'connected': False}


@app.get('/connection/uvpro/devices')
async def uvpro_devices():
    # Same paired-device list as the Bluetooth tab -- a UV-Pro/Benshi
    # radio pairs like any other Bluetooth device, it just needs the
    # different protocol uvpro_tnc.py speaks once connected.
    return {'devices': list_paired_devices(), 'selected': uvpro_client.address}


@app.post('/connection/uvpro/connect')
async def uvpro_connect(address: str = Form(...)):
    uvpro_client.disconnect()
    uvpro_client.address = address.strip()
    save_connection_state()
    try:
        uvpro_client.connect(CALLSIGNS)
        return {'connected': True}
    except Exception as e:
        return {'connected': False, 'error': str(e)}


@app.post('/connection/uvpro/disconnect')
async def uvpro_disconnect():
    uvpro_client.disconnect()
    return {'connected': False}


@app.get('/connection/usb/devices')
async def usb_devices():
    return {'devices': list_serial_ports(), 'selected': usb_client.port}


@app.post('/connection/usb/connect')
async def usb_connect(port: str = Form(...)):
    usb_client.disconnect()
    usb_client.port = port.strip()
    save_connection_state()
    try:
        usb_client.connect(CALLSIGNS)
        return {'connected': True}
    except Exception as e:
        return {'connected': False, 'error': str(e)}


@app.post('/connection/usb/disconnect')
async def usb_disconnect():
    usb_client.disconnect()
    return {'connected': False}


@app.get('/get_positions')
async def get_positions():
    return list(get_active_client().positions.values())


@app.post('/send_position')
async def send_position(request: Request, lat: str = Form(...), lon: str = Form(...), comment: str = Form(''), symbol: str = Form('/-')):
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        symbol_table = symbol[0] if len(symbol) > 0 else '/'
        symbol_code = symbol[1] if len(symbol) > 1 else '-'
        get_active_client().send_position(lat_f, lon_f, comment, symbol_table, symbol_code)
        flash(request, f"Position sent: {lat_f}, {lon_f}")
    except ValueError:
        flash(request, "Invalid latitude/longitude.")
    except Exception as e:
        flash(request, f"Failed to send position: {e}")
    return RedirectResponse(url='/', status_code=303)


@app.post('/clear_messages')
async def clear_messages():
    # Clear the message buffer
    message_history.clear()
    get_active_client().received_messages.clear()
    return {"status": "success", "message": "Message buffer cleared."}


@app.post('/clear_positions')
async def clear_positions():
    # Clear the position buffer -- otherwise it just repopulates from the
    # active client's stored positions on the next poll.
    get_active_client().positions.clear()
    return {"status": "success", "message": "Position buffer cleared."}


@app.get('/license')
async def license_page():
    return PlainTextResponse(Path('LICENSE').read_text())


def main():
    parser = argparse.ArgumentParser(description='APRS Webchat server')
    parser.add_argument('-p', '--port', type=int, default=5001, help='Port to listen on (default: 5001)')
    args = parser.parse_args()
    uvicorn.run(app, host='0.0.0.0', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
