"""RoastMyPost - FastAPI app.

No accounts, no database, no persisted user text - see roast_engine.py
for the privacy design. Rate limiting is in-memory only (resets on
restart) and keyed by IP, which is the only "identifier" this app ever
touches, and only to count requests, never logged to disk.
"""
import os
import time
from collections import defaultdict, deque
from pathlib import Path


def _load_dotenv():
    """Tiny no-dependency .env loader - avoids an extra pip package for
    one file. Does not override already-set real environment variables."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from roast_engine import generate_roast

app = FastAPI(title="RoastMyPost")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

RATE_LIMIT_PER_HOUR = 20
_request_log: dict[str, deque] = defaultdict(deque)


def _rate_limited(ip: str) -> bool:
    now = time.time()
    q = _request_log[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_HOUR:
        return True
    q.append(now)
    return False


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/roast")
async def roast(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if _rate_limited(client_ip):
        return JSONResponse(
            {"error": "Too many roasts this hour - try again later."}, status_code=429
        )
    body = await request.json()
    text = str(body.get("text", ""))[:3000]
    lang = str(body.get("lang", "auto"))
    result = generate_roast(text, lang)
    # `text` goes out of scope here and is never stored.
    return JSONResponse(result)
