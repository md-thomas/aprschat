"""APRS over a UV-Pro/Benshi-class radio's built-in TNC (BTech UV-Pro,
Vero VR-N76, RadioOddity GA5WB, ...), via Bluetooth Classic RFCOMM.

Unlike a real KISS TNC (Mobilinkd TNC3/4, see bluetooth_tnc.py), this
radio doesn't put raw KISS bytes on the wire -- its TNC data rides
inside the same benlink command protocol as everything else, as
fragmented HT_SEND_DATA/DATA_RXD messages capped at 50 bytes/fragment.
This module does the translation, wrapping benlink's asyncio API behind
KissTNCClient's synchronous transport hooks: a dedicated background
event loop thread owns the live benlink connection for the life of the
session, fragmenting outgoing AX.25 frames and reassembling incoming
ones across it, so the shared KISS/AX.25 handling in kiss_tnc.py doesn't
need to know any of this is happening.

Ported from the open_uvpro project (scripts/kiss_bridge.py,
radio_connect.py, discover_channel.py), which found all of this the
hard way against real hardware -- see that project's NOTES.md for the
debugging history. Unlike that project's long-running bridge daemon,
this doesn't auto-reconnect on a dropped link: consistent with
BluetoothTNCClient/SerialTNCClient, a lost connection here just marks
`connected = False` and waits for the user to hit Connect again.
"""

import asyncio
import queue
import threading

import uvpro_patches  # noqa: F401 (applies protocol compatibility patches on import)
from benlink.command import TncDataFragment, TncDataFragmentReceivedEvent
from benlink.controller import RadioController
from kiss import KissDecoder, kiss_encode
from kiss_tnc import KissTNCClient
from uvpro_discover import discover_command_channel

MAX_FRAGMENT_SIZE = 50
SEND_TIMEOUT_SECONDS = 10
OPEN_TIMEOUT_SECONDS = 20
INBOX_POLL_SECONDS = 1

# 0ms TXDELAY/TXTAIL (this radio's factory default) risks keying up and
# sending data before the PA/transmitter has actually stabilized,
# clipping the start of every packet so the far end can't decode it.
# Only applied if the radio's current settings are still 0/0, so it
# never overrides a value the user (or a previous session) already set.
DEFAULT_TX_DELAY = 30  # 10ms units -> 300ms
DEFAULT_TX_TAIL = 5    # 10ms units -> 50ms


class _RadioHandle:
    def __init__(self, loop):
        self.loop = loop
        self.radio = None
        self.inbox = queue.Queue()
        self.close_event = None  # created on the loop thread, in connect()


async def _connect_and_serve(address, handle, ready):
    try:
        channel = discover_command_channel(address)
    except Exception as e:
        ready.put(e)
        return

    try:
        async with RadioController.new_rfcomm(address, channel=channel) as radio:
            if not radio.settings.kiss_en:
                await radio.set_settings(kiss_en=True)
            if radio.settings.kiss_tx_delay == 0 and radio.settings.kiss_tx_tail == 0:
                await radio.set_settings(kiss_tx_delay=DEFAULT_TX_DELAY, kiss_tx_tail=DEFAULT_TX_TAIL)

            handle.radio = radio
            handle.close_event = asyncio.Event()

            reassembly = bytearray()

            def on_event(event):
                nonlocal reassembly
                if isinstance(event, TncDataFragmentReceivedEvent):
                    reassembly += event.tnc_data_fragment.data
                    if event.tnc_data_fragment.is_final_fragment:
                        handle.inbox.put(kiss_encode(bytes(reassembly)))
                        reassembly = bytearray()

            radio.add_event_handler(on_event)

            # The radio's Gaia-protocol read loop can die silently on a
            # stream desync (a real, recurring firmware bug -- see
            # open_uvpro's NOTES.md) without surfacing any error through
            # the normal request/response path. Watch it directly so a
            # death is caught immediately instead of hanging the next
            # send forever waiting for a reply that will never come.
            listen_task = radio._conn._link._client._st.listen_task

            ready.put(handle)

            done, _ = await asyncio.wait(
                {listen_task, asyncio.ensure_future(handle.close_event.wait())},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if listen_task in done and not handle.close_event.is_set():
                exc = listen_task.exception() if not listen_task.cancelled() else None
                handle.inbox.put(exc or ConnectionError("UV-Pro link closed"))
    except Exception as e:
        ready.put(e)


async def _send(radio, payload: bytes) -> None:
    chunks = [
        payload[i:i + MAX_FRAGMENT_SIZE]
        for i in range(0, len(payload), MAX_FRAGMENT_SIZE)
    ] or [b""]
    for i, chunk in enumerate(chunks):
        await asyncio.wait_for(
            radio._conn.send_tnc_data_fragment(TncDataFragment(
                is_final_fragment=(i == len(chunks) - 1),
                fragment_id=i % 64,
                data=chunk,
            )),
            timeout=SEND_TIMEOUT_SECONDS,
        )


class UvProTNCClient(KissTNCClient):
    transport_name = "UV-Pro"

    def __init__(self, callsign, address='', digipath=None):
        super().__init__(callsign, digipath)
        self.address = address

    def _open(self):
        if not self.address:
            raise ConnectionError("No UV-Pro device selected.")

        loop = asyncio.new_event_loop()
        handle = _RadioHandle(loop)
        ready = queue.Queue()

        def run_loop():
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_connect_and_serve(self.address, handle, ready))
            finally:
                loop.close()

        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()

        result = ready.get(timeout=OPEN_TIMEOUT_SECONDS)
        if isinstance(result, Exception):
            raise result
        return handle

    def _read(self, handle):
        try:
            item = handle.inbox.get(timeout=INBOX_POLL_SECONDS)
        except queue.Empty:
            return b""
        if isinstance(item, Exception):
            raise item
        return item

    def _write(self, handle, data):
        for frame in KissDecoder().feed(data):
            payload = frame[1:]  # strip the KISS port/command byte
            future = asyncio.run_coroutine_threadsafe(_send(handle.radio, payload), handle.loop)
            future.result(timeout=SEND_TIMEOUT_SECONDS)

    def _close(self, handle):
        if handle.close_event is not None:
            handle.loop.call_soon_threadsafe(handle.close_event.set)
