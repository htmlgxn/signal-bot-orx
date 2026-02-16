#!/usr/bin/env node

const express = require("express");
const axios = require("axios");
const qrcode = require("qrcode-terminal");
const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");

const PORT = Number(process.env.PORT || 3001);
const BOT_WEBHOOK_URL =
  process.env.BOT_WEBHOOK_URL || "http://127.0.0.1:8001/webhook/whatsapp";
const BRIDGE_TOKEN = (process.env.WHATSAPP_BRIDGE_TOKEN || "").trim();
const AUTH_DIR = process.env.WHATSAPP_AUTH_DIR || ".wwebjs_auth";
const SESSION_NAME = process.env.WHATSAPP_SESSION || "sigbot";

const app = express();
app.use(express.json({ limit: "20mb" }));

function requireBridgeAuth(req, res, next) {
  if (!BRIDGE_TOKEN) {
    next();
    return;
  }

  const auth = String(req.headers.authorization || "");
  if (auth === `Bearer ${BRIDGE_TOKEN}`) {
    next();
    return;
  }

  res.status(401).json({ error: "unauthorized" });
}

const client = new Client({
  authStrategy: new LocalAuth({
    clientId: SESSION_NAME,
    dataPath: AUTH_DIR,
  }),
  puppeteer: {
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  },
});

client.on("qr", (qr) => {
  console.log("Scan this QR with WhatsApp:");
  qrcode.generate(qr, { small: true });
});

client.on("ready", () => {
  console.log("WhatsApp bridge ready");
});

client.on("auth_failure", (msg) => {
  console.error("WhatsApp auth failure:", msg);
});

client.on("disconnected", (reason) => {
  console.warn("WhatsApp disconnected:", reason);
});

client.on("message", async (msg) => {
  try {
    if (msg.fromMe) {
      return;
    }

    const text = (msg.body || "").trim();
    if (!text) {
      return;
    }

    const sender = msg.author || msg.from;
    const chatId = msg.from;
    const payload = {
      from: sender,
      chatId,
      text,
      timestamp: Number(msg.timestamp || 0),
      isGroup: chatId.endsWith("@g.us"),
      message: {
        from: sender,
        chatId,
        text,
        timestamp: Number(msg.timestamp || 0),
      },
    };

    await axios.post(BOT_WEBHOOK_URL, payload, {
      timeout: 15000,
      headers: {
        "content-type": "application/json",
      },
    });
  } catch (err) {
    const detail = err?.response?.data || err?.message || String(err);
    console.error("Webhook forward error:", detail);
  }
});

app.get("/healthz", (_req, res) => {
  res.json({ status: "ok" });
});

app.post("/send/text", requireBridgeAuth, async (req, res) => {
  try {
    const chatId = String(req.body?.chatId || "").trim();
    const text = String(req.body?.text || "").trim();

    if (!chatId || !text) {
      res.status(400).json({ error: "chatId and text are required" });
      return;
    }

    await client.sendMessage(chatId, text);
    res.json({ ok: true });
  } catch (err) {
    const detail = err?.message || String(err);
    res.status(500).json({ error: detail });
  }
});

app.post("/send/image", requireBridgeAuth, async (req, res) => {
  try {
    const chatId = String(req.body?.chatId || "").trim();
    const imageBase64 = String(req.body?.imageBase64 || "").trim();
    const mimeType = String(req.body?.mimeType || "").trim() || "image/jpeg";
    const caption = req.body?.caption ? String(req.body.caption) : undefined;

    if (!chatId || !imageBase64) {
      res.status(400).json({ error: "chatId and imageBase64 are required" });
      return;
    }

    const media = new MessageMedia(mimeType, imageBase64, "image");
    await client.sendMessage(chatId, media, {
      caption,
      sendMediaAsSticker: false,
    });
    res.json({ ok: true });
  } catch (err) {
    const detail = err?.message || String(err);
    res.status(500).json({ error: detail });
  }
});

app.listen(PORT, () => {
  console.log(`WhatsApp bridge listening on :${PORT}`);
  console.log(`Forwarding inbound messages to ${BOT_WEBHOOK_URL}`);
});

client.initialize();
