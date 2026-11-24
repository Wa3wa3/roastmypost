# RoastMyPost

A one-click tool: paste a LinkedIn post, get a short, funny (never mean)
AI roast + a shareable "Cringe Score" card, downloadable as a PNG.
Bilingual (English/Arabic), credited to Waad Ahmed on every card.

## Run it

```
cd "D:/Hermes Agent/roastmypost"
./venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8421
```

Then open http://127.0.0.1:8421

## Setup

1. Copy `.env.example` to `.env`.
2. Put a Gemini API key in it (`GEMINI_API_KEY=...`), from
   https://aistudio.google.com - free tier, no credit card.
3. Without a key, the app still runs and returns varied pre-written roasts
   from `roast_engine.ROAST_BANK_EN` / `ROAST_BANK_AR` instead of calling
   the API - good enough to demo the full click-through experience, but
   not tailored to the actual pasted post.

## Privacy / security design

- The pasted post text is **never written to disk or a database**. It's
  held in memory for one request, sent to the model, and discarded.
- No IP address, name, or other identifier is ever attached to the text
  sent to the model or kept anywhere after the response returns.
- Rate limiting (20 requests/hour per IP) is in-memory only - resets on
  every restart, nothing persisted.
- The model's system prompt forbids attacking protected characteristics,
  profanity, or personal attacks - it's instructed to roast the WRITING
  (buzzwords, humble-brags, LinkedIn tropes), never the person. A second,
  independent keyword blocklist checks the model's output before it's
  ever shown to a user, and fails closed to a safe pre-written roast if
  anything slips through.
- The `html2canvas` CDN script is pinned with a Subresource Integrity
  (SRI) hash, so a compromised CDN can't silently inject different code.

## What's NOT done yet (next steps before a public launch)

- No payment/paywall - currently unlimited free use (rate-limited only).
  Natural next step: Gumroad/Stripe payment link gating unlimited use, or
  a small per-roast credit system.
- No real domain/hosting - currently runs locally only. Needs a cheap VPS
  or PaaS (Render, Railway, Fly.io) to be reachable from the internet.
- No analytics - you won't currently know how many people use it or what
  gets shared.
- Model: using `gemini-3.5-flash`. Re-check available models periodically
  with `client.models.list()` - Google retires/renames models over time
  (see the comment in `roast_engine.py`).
