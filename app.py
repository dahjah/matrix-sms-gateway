import os
import asyncio
from fastapi import FastAPI, Form
from nio import AsyncClient, RoomPreset
from fastapi.responses import JSONResponse
from starlette.requests import Request

app = FastAPI()

# Matrix credentials and homeserver from environment
HOMESERVER = os.getenv("MATRIX_HOMESERVER")
USER_ID = os.getenv("MATRIX_USER_ID")
PASSWORD = os.getenv("MATRIX_PASSWORD")

# Initialize nio client globally and login once on startup
matrix_client = AsyncClient(HOMESERVER, USER_ID)

@app.on_event("startup")
async def startup_event():
    await matrix_client.login(PASSWORD)

@app.on_event("shutdown")
async def shutdown_event():
    await matrix_client.logout()
    await matrix_client.close()

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Service is running"}

async def find_dm_room(client: AsyncClient, target_jid: str):
    rooms = await client.joined_rooms()
    for room_id in rooms.rooms:
        room = client.rooms.get(room_id)
        if room is None:
            await client.room_get_state(room_id)
            room = client.rooms.get(room_id)
        if room and room.is_direct and target_jid in room.users:
            return room_id
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
    print(f"TARGET JID: {target_jid}")

    if len(phone_jid_localpart) == 9:
        phone_jid_localpart = f"1"
    target_jid = f"@_bifrost_=2b{phone_jid_localpart}=40cheogram.com:aria-net.org"
    message = f"{'('+subject+')' if subject else ''} {body_plain}" if body_plain else "(I got a text for you from Salesforce, but it didn't tell me what it was! - Monubot)"

    room_id = await find_dm_room(matrix_client, target_jid)
    if not room_id:
        resp = await matrix_client.room_create(
            invite=[target_jid],
            is_direct=True,
            preset=RoomPreset.private_chat,
        )
        room_id = resp.room_id

    message = f"{body_plain}" if body_plain else "(empty message)"
    await matrix_client.room_send(
        room_id,
        message_type="m.room.message",
        content={
            "msgtype": "m.text",
            "body": message,
        }
    )

    return JSONResponse({"status": "SMS sent", "to": target_jid})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
