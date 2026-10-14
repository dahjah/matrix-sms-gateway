# Email to Matrix SMS Gateway

With many cell providers closing down their email-to-text gateways, this project serves as a **self-hostable almost-equivalent solution**.

Matrix-SMS-Gateway is a simple **FastAPI** server built to receive incoming POST requests from an SMTP server or email webhook (e.g., Mailgun). It relays those messages to a connected Matrix account, which is tied to a JMP.chat phone number, thereby enabling SMS sending via Matrix.


## Setup

Everything should be fairly straightforward to set up:

### Prerequisites

- A Matrix account connected to JMP.chat (your phone number bridged as a Matrix user).
- An SMTP server or email forwarding service configured to send inbound emails as POST requests.
- Python 3.11+ (if running locally) or Docker compatible environment.
- Optional: Mailgun account for inbound message forwarding.

### Installation

You can run the gateway in several ways:

#### 1. Using Docker

Build and run with your preferred tool (e.g., Docker Compose):

```
docker build -t matrix-sms-gateway .
docker run -e MATRIX_HOMESERVER="https://aria-net.org"
-e MATRIX_USER_ID="@user:aria-net.org"
-e MATRIX_PASSWORD="your_password"
-p 8080:8080
matrix-sms-gateway
```


#### 2. Running Locally

Install requirements and launch:

```
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080
```


### Configuration

Set environment variables to connect the gateway to your Matrix account:

- `MATRIX_HOMESERVER` — Your homeserver URL (e.g., https://aria-net.org)
- `MATRIX_USER_ID` — Your full Matrix user ID (e.g., @user:aria-net.org)
- `MATRIX_PASSWORD` — Your Matrix account password or access token

#### XMPP backend (alternative to Matrix)

JMP.chat is natively XMPP, so you can skip Matrix entirely. Set `MESSAGING_BACKEND=xmpp` (default is `matrix`) and provide:

- `XMPP_JID` — Your XMPP account JID (e.g., user@example.com). It must be registered with JMP.chat.
- `XMPP_PASSWORD` — Your XMPP account password
- `XMPP_GATEWAY_DOMAIN` — SMS gateway domain (default `cheogram.com`); messages go to `+<number>@cheogram.com`

#### Webhook authentication (required)

`/mailgun-webhook` rejects every request unless it carries the shared secret in `WEBHOOK_TOKEN`:

- `WEBHOOK_TOKEN` — a long random string (e.g., `openssl rand -hex 32`). If unset, all webhook requests are rejected (HTTP 503).
- Send it either as a query parameter (`/mailgun-webhook?token=...`) or an `X-Webhook-Token` header. For Mailgun, put it in the route URL: `forward("https://your-host/mailgun-webhook?token=...")`.
- Use https so the token isn't sent in clear text. `/health` stays unauthenticated.

### Mailgun Setup (Optional)

1. Create an inbound route for your receiving email domain.
2. Forward inbound messages as HTTP POST to your gateway's `/mailgun-webhook` endpoint.
3. Configure Mailgun to send the form fields `recipient`, `subject`, and `body-plain` in the request.

---

## Example Docker Compose Setup

```
version: "3.9"

services:
matrix-sms-gateway:
build: .
container_name: matrix-sms-gateway
environment:
MATRIX_HOMESERVER: "https://aria-net.org"
MATRIX_USER_ID: "@user:aria-net.org"
MATRIX_PASSWORD: "your_password"
ports:
- "8080:8080"
restart: unless-stopped
```


Run with:

```
docker-compose up -d
```


---

## Mailgun Integration Example

### Steps to set up Mailgun inbound email routing:

1. In [Mailgun Control Panel > Routes](https://app.mailgun.com/app/routes), create a new route:

   - **Filter expression:** `match_recipient("your-phone-number@yourdomain.com")` (or use a wildcard or catch-all to allow all phone numbers)
   - **Actions:** `forward("http://your-server-ip-or-domain:8080/mailgun-webhook")`
   - **Description:** "Forward SMS emails to Matrix SMS Gateway"

2. **Test sending an email** to your forwarded address (e.g., `14155551212@yourdomain.com`).

3. The gateway receives the POST request, extracts recipient number, message body, and forwards as SMS.

---

## Testing with curl

You can simulate Mailgun’s webhook POST for quick testing:

```
curl -X POST http://localhost:8080/mailgun-webhook
-F recipient="14155551212@yourdomain.com"
-F subject="Test SMS"
-F "body-plain=Hello from Mailgun!"
```

Because the system only relies on those three form fields, you can also use this with any system that can send a POST request, not just mailgun or other SMTP service.
