import argparse
import configparser
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from aprs import APRSClient
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

# Saved callsigns shown in the sidebar, editable from the web page
CALLSIGNS_FILE = Path('callsigns.json')


def load_callsigns():
    if CALLSIGNS_FILE.exists():
        with open(CALLSIGNS_FILE) as f:
            return json.load(f)
    return []


def save_callsigns(callsigns):
    with open(CALLSIGNS_FILE, 'w') as f:
        json.dump(callsigns, f, indent=2)


CALLSIGNS = load_callsigns()

aprs_client = APRSClient(CALLSIGN, PASSCODE)
aprs_client.connect()
aprs_client.listen_for_messages()

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
    # Include both sent and received messages in the view
    chat_history = message_history + [
        {'to': aprs_client.callsign, 'msg': msg['msg'], 'time': msg['time'], 'direction': 'in'}
        for msg in aprs_client.received_messages
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

    total_sends = len(recipients) * len(chunks)
    sent = 0
    for recipient in recipients:
        for chunk in chunks:
            sent += 1
            try:
                aprs_client.send_message(recipient, chunk)
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
    # Get both sent and received messages
    chat_history = message_history + [
        {
            'from': msg.get('from', 'Unknown'),
            'to': aprs_client.callsign,
            'msg': msg['msg'],
            'msgid': msg['msgid'],
            'time': msg['time'],
            'direction': 'in'
        }
        for msg in aprs_client.received_messages
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
    return RedirectResponse(url='/', status_code=303)


@app.post('/callsigns/remove')
async def remove_callsign(callsign: str = Form(...)):
    cs = callsign.strip().upper()
    if cs in CALLSIGNS:
        CALLSIGNS.remove(cs)
        save_callsigns(CALLSIGNS)
    return RedirectResponse(url='/', status_code=303)


@app.post('/clear_messages')
async def clear_messages():
    # Clear the message buffer
    message_history.clear()
    aprs_client.received_messages.clear()
    return {"status": "success", "message": "Message buffer cleared."}


def main():
    parser = argparse.ArgumentParser(description='APRS Webchat server')
    parser.add_argument('-p', '--port', type=int, default=5001, help='Port to listen on (default: 5001)')
    args = parser.parse_args()
    uvicorn.run(app, host='0.0.0.0', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
