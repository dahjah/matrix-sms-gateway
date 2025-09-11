import os
import asyncio
from fastapi import FastAPI, Form
from fastapi.responses import JSONResponse

import niobot

app = FastAPI()

# Matrix credentials and homeserver from environment
HOMESERVER = os.getenv("MATRIX_HOMESERVER")
USER_ID = os.getenv("MATRIX_USER_ID")
PASSWORD = os.getenv("MATRIX_PASSWORD")

# Initialize NioBot globally
bot = niobot.NioBot(
    homeserver=HOMESERVER,
    user_id=USER_ID,
    password=PASSWORD,
)

@app.on_event("startup")
async def startup_event():
    await bot.login()

@app.on_event("shutdown")
async def shutdown_event():
    await bot.logout()
    await bot.close()

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Service is running"}

@app.post("/mailgun-webhook")
async def mailgun_webhook(
    recipient: str = Form(...),
    subject: str = Form(""),
    body_plain: str = Form("", alias="body-plain"),
):
    phone_jid_localpart = recipient.split("@")[0]
    if len(phone_jid_localpart) == 9:
        phone_jid_localpart = f"1{phone_jid_localpart}"
    target_jid = f"@_bifrost_=2b{phone_jid_localpart}=40cheogram.com:aria-net.org"
    message = f"{'('+subject+')' if subject else ''} {body_plain}" if body_plain else "(I got a text for you from Salesforce, but it didn't tell me what it was! - Monubot)"

    # Try to find existing DM rooms
    rooms = await bot.get_dm_rooms(target_jid)
    if rooms:
        room_id = rooms[0]
    else:
        # Create DM room; Matrix generates the room_id
        response = await bot.create_dm_room(target_jid)
        room_id = response.room_id
        # Set human-readable room name
        room_name = f"Email->SMS with {phone_jid_localpart}"
        await bot.client.room_put_state(
            room_id,
            "m.room.name",
            {"name": room_name}
        )

    # Send message to the direct room
    await bot.send_message(room_id, message)

    return JSONResponse({"status": "SMS sent", "to": target_jid, "room_id": room_id})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
