import asyncio
from typing import Optional

import slixmpp


class XmppSender:
    """
    Maintains one persistent XMPP connection and sends chat messages to
    JIDs such as +13852391367@cheogram.com (the JMP.chat / Cheogram SMS gateway).
    slixmpp handles reconnecting automatically; we only track readiness.
    """

    def __init__(self, jid: str, password: str, ready_timeout: float = 20.0):
        self.ready_timeout = ready_timeout
        self._ready = asyncio.Event()
        self.client = slixmpp.ClientXMPP(jid, password)
        self.client.register_plugin("xep_0199")  # keepalive pings
        self.client.add_event_handler("session_start", self._on_session_start)
        self.client.add_event_handler("disconnected", self._on_disconnected)
        self.client.add_event_handler("failed_auth", self._on_failed_auth)
        self.client.add_event_handler("message", self._on_message)
        self.client.add_event_handler("message_error", self._on_message_error)

    def _on_message(self, msg):
        print(f"INFO: XMPP message from {msg['from']}: {msg['body']}")

    def _on_message_error(self, msg):
        print(f"ERROR: XMPP delivery error from {msg['from']}: {msg['error']['condition']} {msg['error']['text']}")

    async def _on_session_start(self, _event):
        self.client.send_presence()
        self._ready.set()
        print(f"INFO: XMPP session started as {self.client.boundjid.bare}")

    def _on_disconnected(self, _event):
        self._ready.clear()
        print("WARNING: XMPP disconnected")

    def _on_failed_auth(self, _event):
        print("ERROR: XMPP authentication failed")

    def start(self):
        self.client.connect()

    async def stop(self):
        self.client.disconnect()
        try:
            await asyncio.wait_for(self.client.disconnected, timeout=5)
        except Exception:
            pass

    async def send(self, to_jid: str, body: str) -> Optional[str]:
        """Send a message. Returns None on success, or an error string."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self.ready_timeout)
        except asyncio.TimeoutError:
            return "XMPP connection not ready"
        self.client.send_message(mto=to_jid, mbody=body, mtype="chat")
        return None
