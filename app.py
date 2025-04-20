from flask import Flask, render_template, request, redirect, flash, url_for, jsonify
from aprs import APRSClient
from datetime import datetime
import logging
import configparser

app = Flask(__name__)
app.secret_key = 'the_secret_key'

# Suppress the default request logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR) 

# Replace with your actual callsign and password
config = configparser.ConfigParser()
config.read('aprschat.config')
CALLSIGN = config['settings']['callsign']
PASSCODE = config['settings']['passcode']

aprs_client = APRSClient(CALLSIGN, PASSCODE)
aprs_client.connect()
aprs_client.listen_for_messages()

# In-memory history (clears when the app restarts)
message_history = []

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        to_callsign = request.form['to_callsign']
        message = request.form['message']
        if len(message) > 61:
            flash(f"Message was too long and has been truncated to 61 characters...")
            print(f"[WARNING] Message too long. Trimming to 61 characters.")
            message = message[:61]
        try:
            aprs_client.send_message(to_callsign, message)
            message_history.append({
                'to': to_callsign.upper(),
                'msg': message,
                # 'msgid': msgid,
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'direction': 'out'
            })
        except Exception as e:
            message_history.append({
                'to': to_callsign.upper(),
                'msg': f"[ERROR] {str(e)}",
                # 'msgid': msgid,
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'direction': 'out'
            })
        return redirect(url_for('index'))

    # Include both sent and received messages in the view
    chat_history = message_history + [
        {'to': aprs_client.callsign, 'msg': msg['msg'], 'time': msg['time'], 'direction': 'in'}
        for msg in aprs_client.received_messages
    ]

    # Sort by time if needed, for now just show in order
    return render_template('index.html', history=chat_history)

@app.route('/get_messages')
def get_messages():
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

    # print("[DEBUG] Received Messages:", chat_history)
    # Return the messages as JSON
    return jsonify(chat_history)

@app.route('/clear_messages', methods=['POST'])
def clear_messages():
    # Clear the message buffer
    global message_history
    message_history.clear()
    aprs_client.received_messages.clear()
    # Return a success message
    return jsonify({"status": "success", "message": "Message buffer cleared."})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
