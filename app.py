import os
from typing import Dict, Optional
import json
import asyncio
from fastapi import FastAPI, Form
from nio import AsyncClient, RoomPreset, RoomCreateError, LoginError, RoomGetStateError
from fastapi.responses import JSONResponse
from starlette.requests import Request

app = FastAPI()

# Which backend delivers the SMS: "matrix" (default) or "xmpp"
BACKEND = os.getenv("MESSAGING_BACKEND", "matrix").lower()

# Matrix credentials and homeserver from environment
HOMESERVER = os.getenv("MATRIX_HOMESERVER")
USER_ID = os.getenv("MATRIX_USER_ID")
PASSWORD = os.getenv("MATRIX_PASSWORD")

# XMPP credentials and SMS gateway domain from environment
XMPP_JID = os.getenv("XMPP_JID")
XMPP_PASSWORD = os.getenv("XMPP_PASSWORD")
XMPP_GATEWAY_DOMAIN = os.getenv("XMPP_GATEWAY_DOMAIN", "cheogram.com")
xmpp_sender = None

# File-backed cache: maps target_jid -> room_id so we never need to
# scan all rooms or call createRoom for recipients we've seen before.
ROOM_CACHE_FILE = os.getenv("ROOM_CACHE_FILE", "/app/room_cache.json")
room_cache: Dict[str, str] = {}

def load_room_cache():
    global room_cache
    try:
        with open(ROOM_CACHE_FILE) as f:
            room_cache = json.load(f)
        print(f"INFO: Loaded {len(room_cache)} entries from room cache")
    except FileNotFoundError:
        room_cache = {}
    except Exception as e:
        print(f"WARNING: Could not load room cache: {e}")
        room_cache = {}

def save_room_cache():
    try:
        with open(ROOM_CACHE_FILE, "w") as f:
            json.dump(room_cache, f, indent=2)
    except Exception as e:
        print(f"WARNING: Could not save room cache: {e}")

# Initialize nio client globally and login once on startup
matrix_client = AsyncClient(HOMESERVER, USER_ID) if BACKEND == "matrix" else None

@app.on_event("startup")
async def startup_event():
    global xmpp_sender
    if BACKEND == "xmpp":
        from xmpp_backend import XmppSender
        xmpp_sender = XmppSender(XMPP_JID, XMPP_PASSWORD)
        xmpp_sender.start()
        print(f"INFO: Starting XMPP backend as {XMPP_JID}")
        return
    load_room_cache()
    resp = await matrix_client.login(PASSWORD)
    if isinstance(resp, LoginError):
        print(f"ERROR: Matrix login failed at startup: {resp.message}")
    else:
        print(f"INFO: Logged into Matrix as {USER_ID}")

async def ensure_logged_in():
    """Re-login if the access token has expired."""
    if not matrix_client.access_token:
        print("INFO: No access token, re-logging in to Matrix...")
        resp = await matrix_client.login(PASSWORD)
        if isinstance(resp, LoginError):
            print(f"ERROR: Matrix re-login failed: {resp.message}")
            return False
    return True

@app.on_event("shutdown")
async def shutdown_event():
    if BACKEND == "xmpp":
        if xmpp_sender:
            await xmpp_sender.stop()
        return
    await matrix_client.logout()
    await matrix_client.close()

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Service is running"}

async def find_dm_room(client: AsyncClient, target_jid: str) -> Optional[str]:
    """
    Scan joined rooms via the Matrix API to find an existing DM room
    with target_jid. Checks room members directly via the API rather
    than relying on the local sync cache (which is empty without sync).
    """
    rooms_resp = await client.joined_rooms()
    if hasattr(rooms_resp, 'message'):  # error response
        print(f"WARNING: joined_rooms() failed: {rooms_resp.message}")
        return None

    for room_id in rooms_resp.rooms:
        try:
            members_resp = await client.joined_members(room_id)
            if hasattr(members_resp, 'message'):
                continue
            if target_jid in members_resp.members:
                print(f"INFO: Found existing DM room {room_id} for {target_jid}")
                return room_id
        except Exception as e:
            print(f"WARNING: Error checking members of {room_id}: {e}")
            continue
    return None

@app.post("/mailgun-webhook")
async def mailgun_webhook(
    request: Request,
    recipient: str = Form(...),
    subject: str = Form(""),
    body_plain: str = Form("", alias="body-plain"),
):
    phone_jid_localpart = recipient.split("@")[0]

    print(f"RECIPIENT: {recipient}\nSUBJECT: {subject}\nBODY: {body_plain}")

    if len(phone_jid_localpart) == 9:
        phone_jid_localpart = f"1{phone_jid_localpart}"
    message = f"{'('+subject+')' if subject else ''} {body_plain}".strip() if body_plain else "(I got a text for you from Salesforce, but it didn't tell me what it was! - Monubot)"

    if BACKEND == "xmpp":
        xmpp_jid = f"+{phone_jid_localpart}@{XMPP_GATEWAY_DOMAIN}"
        err = await xmpp_sender.send(xmpp_jid, message)
        if err:
            print(f"ERROR: XMPP send to {xmpp_jid} failed: {err}")
            return JSONResponse({"status": "error", "detail": err}, status_code=502)
        print(f"INFO: Sent XMPP message to {xmpp_jid}")
        return JSONResponse({"status": "SMS sent", "to": xmpp_jid})

    target_jid = f"@_bifrost_=2b{phone_jid_localpart}=40cheogram.com:aria-net.org"

    # 1. Check the fast in-memory/file cache first
    room_id = room_cache.get(target_jid)

    # 2. If not cached, scan existing rooms (slow but avoids createRoom)
    if not room_id:
        print(f"INFO: No cached room for {target_jid}, scanning joined rooms...")
        room_id = await find_dm_room(matrix_client, target_jid)
        if room_id:
            room_cache[target_jid] = room_id
            save_room_cache()

    # 3. If still no room, create one
    if not room_id:
        if not await ensure_logged_in():
            return JSONResponse({"status": "error", "detail": "Matrix login failed"}, status_code=502)

        print(f"INFO: Creating new DM room for {target_jid}...")
        resp = await matrix_client.room_create(
            invite=[target_jid],
            is_direct=True,
            preset=RoomPreset.private_chat,
        )
        if isinstance(resp, RoomCreateError):
            status = getattr(resp.transport_response, 'status', None)
            print(f"ERROR: Failed to create Matrix room for {target_jid}: http={status} status_code={resp.status_code!r} message={resp.message!r}")
            return JSONResponse(
                {"status": "error", "detail": f"Matrix room creation failed (HTTP {status}): {resp.message}"},
                status_code=502,
            )
        room_id = resp.room_id
        room_cache[target_jid] = room_id
        save_room_cache()
        print(f"INFO: Created room {room_id} for {target_jid}")

    resp = await matrix_client.room_send(
        room_id,
        message_type="m.room.message",
        content={
            "msgtype": "m.text",
            "body": message,
        }
    )
    print(f"INFO: Sent message to {room_id}, event_id={getattr(resp, 'event_id', '?')}")

    return JSONResponse({"status": "SMS sent", "to": target_jid, "room_id": room_id})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
