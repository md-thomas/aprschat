# README
This is my attempt at creating an aprs chat service. 
This uses FastAPI as the backend for the html front end 

# INSTALL
Requirements: python3 and some python modules
You need to run the install.sh script to setup the 
python virtual environment. This will install the 
needed python modules locally. 

# CONFIG 
Edit the aprschat.config file 
Enter your callsign and aprs passcode 
This url can be used to get your aprs passcode
https://apps.magicbug.co.uk/passcode/

# BLUETOOTH TNC SETUP
The Connection panel's Bluetooth mode talks directly to a classic
Bluetooth (RFCOMM/SPP) KISS TNC -- a Mobilinkd TNC3/TNC4, or a radio
with a built-in KISS-over-Bluetooth passthrough such as the
BTech/Vero UV-Pro. It uses Python's `socket.AF_BLUETOOTH`, which is
Linux-only and needs the BlueZ stack (`bluetoothd`) running.

## Requirements
Install BlueZ and its command-line tools (Debian/Ubuntu):

    sudo apt install bluez bluez-tools

This provides `bluetoothctl` (pairing, device list) and `sdptool`
(service/channel discovery), both of which the app's device picker
and channel auto-detection shell out to (see bluetooth_tnc.py and
rfcomm_connect.py). No extra Python package is needed -- classic
Bluetooth support comes from the standard library on Linux.

Make sure the Bluetooth service is running:

    sudo systemctl status bluetooth

## Pairing the radio
The device only needs to be paired and trusted once -- the app opens
its own RFCOMM connection each time you hit Connect in the panel, it
doesn't rely on an active `bluetoothctl connect` session.

1. Put the radio in Bluetooth pairing/discoverable mode (on a UV-Pro,
   enable Bluetooth in the radio's settings/companion app and make it
   discoverable).
2. On the machine running aprschat:

       bluetoothctl
       power on
       agent on
       default-agent
       scan on
       # wait for the radio to show up, e.g. "Device 38:D2:00:01:85:BF UV-PRO"
       scan off
       pair 38:D2:00:01:85:BF
       trust 38:D2:00:01:85:BF
       exit

3. Refresh the Connection panel's Bluetooth device dropdown -- the
   radio should now appear. Pick it and hit Connect. (You can also
   set its MAC address as the default in aprschat.config's
   `[bluetooth] address` if you always use the same radio.)

## Useful bluetoothctl / sdptool commands for testing
    bluetoothctl devices Paired                    # paired devices + MAC addresses
    bluetoothctl devices Connected                  # what's connected at the BT level right now
    bluetoothctl info <MAC address>                 # pairing/trust/connection state for one device
    sdptool records <MAC address>                   # every SDP service the device advertises
    sdptool search --bdaddr <MAC address> SP        # find the Serial Port (SPP) RFCOMM channel --
                                                     # this is what rfcomm_connect.py runs automatically
                                                     # when aprschat.config's [bluetooth] channel is blank
    rfcomm connect 0 <MAC address> <channel>        # manually open/test the RFCOMM link outside the
                                                     # app; Ctrl-C to release it before connecting from
                                                     # aprschat, since only one client can hold the channel

If `sdptool search ... SP` doesn't find a Serial Port record, check the
radio's Bluetooth/APRS settings for a KISS or "serial passthrough"
mode -- some radios only expose that RFCOMM service once it's enabled.

Note: this Bluetooth mode is for an actual KISS TNC (Mobilinkd TNC3/4,
or similar) that puts raw KISS bytes on the wire. A UV-Pro/Benshi-class
radio (BTech UV-Pro, Vero VR-N76, RadioOddity GA5WB) does **not** --
use the separate "UV-Pro (Bluetooth)" mode below for those.

## UV-Pro / Benshi-class radios

These radios' built-in TNC doesn't speak raw KISS over its RFCOMM
port -- its data rides inside the same proprietary command protocol
("benlink"/Gaia) as everything else (battery, channel list, GPS, ...),
fragmented into ≤50-byte chunks. The "UV-Pro (Bluetooth)" Connection
panel mode (`uvpro_tnc.py`) speaks that protocol directly, using
[benlink](https://github.com/khusmann/benlink) (installed from GitHub
`main`, not PyPI -- see requirements.txt; needs `git` available at
install time).

Setup is the same pairing steps as above (`bluetoothctl pair`/`trust`),
then pick the radio from the "UV-Pro (Bluetooth)" mode's device
dropdown instead of "Bluetooth". A few things specific to this
protocol, found the hard way (see the sibling `open_uvpro` project's
NOTES.md for the full debugging history):

- The radio's command-channel RFCOMM number **floats between
  sessions** (seen as 1, 2, 4 on the same radio) -- `uvpro_discover.py`
  re-probes it live on every connect rather than trusting SDP.
- The radio's Bluetooth stack **refuses a fresh reconnect for a while
  after a disconnect**. If Connect fails right after a Disconnect,
  wait ~15-20s and try again.
- KISS TXDELAY/TXTAIL default to 300ms/50ms on connect if the radio's
  own settings are still at the factory 0/0, since 0ms risks clipping
  the start of every transmitted packet.

# STARTUP
./start.sh will kick off the FastAPI backend server (via uvicorn)
that listens for messages being send and received on
the aprs network. 

Once the application is running you can open a web 
page http://localhost:5001  or http://<your-ip-address:5001

The application runs on port 5001 by default. Use -p to pick a
different port, e.g. ./start.sh -p 8080

# RUN AS A SYSTEMD SERVICE
A sample unit file, aprschat.service, is included so the app can be
managed with systemctl and start automatically on boot, instead of
running it by hand with ./start.sh.

It assumes the repo lives at /home/mdthomas/Projects/aprschat and runs
as the mdthomas user -- edit User/Group/WorkingDirectory/ExecStart in
the file first if either is different for your setup. It also assumes
the venv from `./install.sh` already exists at ./venv.

Install and enable it:

    sudo cp aprschat.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now aprschat

Manage it:

    sudo systemctl start aprschat
    sudo systemctl stop aprschat
    sudo systemctl restart aprschat
    sudo systemctl status aprschat
    journalctl -u aprschat -f      # follow the logs

After editing aprschat.config, the site, or the code, restart the
service to pick up the change:

    sudo systemctl restart aprschat

If you change /etc/systemd/system/aprschat.service itself (a
different port, path, or user), run `sudo systemctl daemon-reload`
before the next start/restart so systemd notices.

# Todo 
1. [x] Keep last used callsign 
2. [x] Add users callsign to page somewhere
3. [x] Add version to page somewhere
4. [x] Add warning if more than 67 characters used in message
5. [x] maybe split messages larger than 67 characters into multiple messages 
6. [x] create a group of callsigns to send messages to
7. [x] add a map to show a location for users
8. [x] add a send position button 

# Credits
Map station icons are from the aprs.fi open APRS symbol set:
https://github.com/hessu/aprs-symbols
That set combines symbols under several licenses (CC BY-SA 2.0,
public domain, and some with undocumented origins) -- see its
COPYRIGHT.md for the breakdown per symbol. The MIT license in this
repo's LICENSE file covers aprschat's own code, not those icons.

# License
aprschat itself is released under the MIT License -- see LICENSE.
