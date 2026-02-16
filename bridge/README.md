# WhatsApp Bridge (whatsapp-web.js)

Minimal bridge for `signal-bot-orx` WhatsApp support.

## 1. Install deps

```bash
cd bridge
npm init -y
npm install express axios qrcode-terminal whatsapp-web.js
```

## 2. Run bridge

```bash
BOT_WEBHOOK_URL=http://127.0.0.1:8001/webhook/whatsapp \
WHATSAPP_BRIDGE_TOKEN= \
node whatsapp-bridge.js
```

Scan the QR code shown in terminal.

## 3. Bot `.env`

Set in your bot:

```env
WHATSAPP_ENABLED=true
WHATSAPP_BRIDGE_BASE_URL=http://127.0.0.1:3001
WHATSAPP_BRIDGE_TOKEN=
WHATSAPP_ALLOWED_NUMBERS=user@c.us
WHATSAPP_DISABLE_AUTH=false
```

For quick testing:

```env
WHATSAPP_DISABLE_AUTH=true
```

## API exposed by bridge

- `GET /healthz`
- `POST /send/text` body: `{ "chatId": "...", "text": "..." }`
- `POST /send/image` body: `{ "chatId": "...", "imageBase64": "...", "mimeType": "image/jpeg", "caption": "..." }`

If `WHATSAPP_BRIDGE_TOKEN` is set, `Authorization: Bearer <token>` is required on `/send/*`.
