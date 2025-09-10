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

@app.post("/mailgun-webhook")
async def mailgun_webhook(
    request: Request,
    recipient: str = Form(...),    # 'recipient' field from Mailgun webhook, e.g. 14155551212@yourdomain.com
    subject: str = Form(""),
    body_plain: str = Form("", alias="body-plain"),
):
    print(f"RECIPIENT: {recipient}\nSUBJECT: {subject}\nBODY: {body_plain}")
    # Extract phone number from recipient email
    phone_jid_localpart = recipient.split("@")[0]
    print(f"JID LOCALPART: {phone_jid_localpart}")
    # Assuming your bridge uses cheogram.com domain for XMPP JIDs
    target_jid = f"@_bifrost_=2b{phone_jid_localpart}=40cheogram.com:aria-net.org"
    print(f"TARGET JID: {target_jid}")

    # Find or create direct message room with bridged target user
    resp = await matrix_client.room_create(
        invite=[target_jid],
        is_direct=True,
        preset=RoomPreset.private_chat,
    )
    print(f"MTX RESP: {resp}")
    room_id = resp.room_id

    print(f"ROOM ID: {room_id}")

    # Compose SMS body (you could prepend subject if needed)
    message = f"{body_plain}" if body_plain else "(empty message)"

    print(f"MESSAGE: {message}")

    # Send the message to the Matrix bridged user
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
