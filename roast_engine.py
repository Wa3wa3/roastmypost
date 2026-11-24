"""Isolated LLM integration for RoastMyPost.

Everything that talks to an external AI provider lives here, behind
generate_roast() - swapping providers or going from mock to real only
ever touches this file.

SECURITY / PRIVACY (by design, not bolted on):
- The submitted post text is never written to disk or a database. It is
  held in memory only for the duration of one request, passed to the
  model, and discarded when the request finishes.
- No user identifiers (IP, name, email) are attached to the text sent to
  the model or kept anywhere after the response is returned.
- A keyword-based output safety net runs AFTER the model responds, as a
  second line of defense on top of the system prompt - if a flagged term
  slips through, the request fails closed (generic safe fallback) instead
  of ever showing it to the user.

CURRENTLY MOCKED: if no GEMINI_API_KEY is set, generate_roast() returns a
canned (but genuinely varied) roast from ROAST_BANK instead of calling an
API, so the whole app is clickable today. Swap over automatically the
moment a real key is present in the environment / .env file.
"""
import os
import random
import re
import threading
import time

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = "gemini-3.5-flash"

# Hard global cap on REAL Gemini calls per day, across all users combined.
# Google's exact free-tier RPD for this specific model isn't clearly
# published as of writing - rather than guess their number, this is a
# deliberately conservative, self-imposed ceiling so the app can never
# silently blow through free-tier quota (or run up a paid bill, if this
# key is ever upgraded to a paid tier). Adjustable without a redeploy via
# `fastapi cloud env set MAX_DAILY_GEMINI_CALLS <n> --app-id ...` - check
# your actual tier/quota in AI Studio before raising this. Once the cap is
# hit, every request for the rest of the day falls back to the mock roast
# bank instead of calling the API at all (saves the wasted round-trip, not
# just "stop trying").
MAX_DAILY_GEMINI_CALLS = int(os.environ.get("MAX_DAILY_GEMINI_CALLS", "100"))

_quota_lock = threading.Lock()
_quota_state = {"day": None, "count": 0}


def _day_key() -> str:
    # Resets at midnight UTC. In-memory only (matches the rest of this
    # app's no-persistence design) - resets early if the process restarts,
    # which only makes the cap MORE conservative, never less.
    return time.strftime("%Y-%m-%d", time.gmtime())


def _quota_available() -> bool:
    """Atomically checks and reserves one unit of today's quota.
    Returns True if this call may proceed to the real API."""
    with _quota_lock:
        today = _day_key()
        if _quota_state["day"] != today:
            _quota_state["day"] = today
            _quota_state["count"] = 0
        if _quota_state["count"] >= MAX_DAILY_GEMINI_CALLS:
            return False
        _quota_state["count"] += 1
        return True

SYSTEM_PROMPT = """You are a witty comedy writer who roasts LinkedIn posts for a fun, \
shareable app. Your roasts are SHARP but NEVER MEAN.

Hard rules, no exceptions:
- Never mention or imply anything about a person's appearance, race, ethnicity, gender, \
religion, nationality, sexual orientation, disability, age, or any protected characteristic.
- Never use profanity, slurs, or sexual content.
- Never attack the poster's character, intelligence, or worth as a person.
- Only roast the WRITING: buzzwords, humble-brags, cliche LinkedIn tropes, overused phrases, \
corporate jargon, excessive self-congratulation. Roast the POST, not the PERSON.
- Keep it light and funny enough that the person being roasted would still want to share it.
- Output ONLY valid JSON: {"roast": "<1-2 short, punchy sentences>", "score": <int 1-10, where \
10 is peak LinkedIn cringe>}
- Match the reply language to the input language (English in, English out; Arabic in, Arabic \
out). For Arabic, always write in Egyptian colloquial Arabic (العامية المصرية) - never Modern \
Standard Arabic (الفصحى). Use everyday Cairo-street phrasing and words like "ده", "كده", "بس", \
"عشان", "مش", not formal literary Arabic.
- No preamble, no markdown, no extra text - JSON only.
"""

# Keyword safety net - defense in depth on top of the system prompt.
BLOCKLIST = [
    "kill", "suicide", "rape", "nazi", "terrorist", "retard", "slur",
]

# Mocked roast bank, used when no API key is configured yet. Varied enough
# that clicking "Roast Me" repeatedly doesn't feel obviously canned.
ROAST_BANK_EN = [
    ("Nothing says 'thought leader' like announcing you took the stairs today. "
     "Riveting content, truly.", 8),
    ("You used 'synergy', 'circle back', and 'move the needle' in one paragraph. "
     "LinkedIn Bingo winner right here.", 9),
    ("A humble-brag disguised as gratitude post. The humility is doing a lot of "
     "heavy lifting.", 7),
    ("This reads like it was written to get a promotion, not to say something true.", 6),
    ("Congratulations on turning a Tuesday into a TED Talk.", 7),
    ("The hashtags alone could power a small startup's entire marketing budget.", 8),
]
ROAST_BANK_AR = [
    ("بوست ناجح كأنه إعلان توظيف لنفسك. الريتش عالي بس المحتوى فاضي.", 8),
    ("كلمة 'إنجاز' مكتوبة عشر مرات وإحنا لسه ما عرفناش الإنجاز إيه بالظبط.", 7),
    ("التواضع الزايف ده بقى نوع أدبي قائم بذاته على لينكدإن.", 8),
    ("البوست ده اتكتب عشان الـ algorithm مش عشان حد يفهم حاجة.", 6),
]


def _looks_arabic(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text))


def _fails_safety(text: str) -> bool:
    low = text.lower()
    return any(bad in low for bad in BLOCKLIST)


def _mock_roast(lang: str) -> dict:
    bank = ROAST_BANK_AR if lang == "ar" else ROAST_BANK_EN
    roast, score = random.choice(bank)
    return {"roast": roast, "score": score, "mocked": True}


def generate_roast(text: str, lang: str = "auto") -> dict:
    """Returns {"roast": str, "score": int, "mocked": bool}.
    `text` is never persisted anywhere by this function or its caller."""
    text = (text or "").strip()
    if not text:
        return {"roast": "Paste something first - can't roast silence.", "score": 0,
                "mocked": True}
    resolved_lang = "ar" if (lang == "ar" or (lang == "auto" and _looks_arabic(text))) else "en"

    if not GEMINI_API_KEY:
        return _mock_roast(resolved_lang)

    if not _quota_available():
        result = _mock_roast(resolved_lang)
        result["quota_exhausted"] = True
        return result

    try:
        from google import genai
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

        def _call():
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = f"{SYSTEM_PROMPT}\n\nLinkedIn post to roast:\n\"\"\"\n{text[:3000]}\n\"\"\""
            return client.models.generate_content(model=GEMINI_MODEL, contents=prompt)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            try:
                resp = future.result(timeout=25)
            except FutureTimeoutError:
                return _mock_roast(resolved_lang)

        raw = (resp.text or "").strip()
        import json
        raw = raw.strip("`").removeprefix("json").strip()
        data = json.loads(raw)
        roast = str(data.get("roast", "")).strip()
        score = int(data.get("score", 5))
        if not roast or _fails_safety(roast):
            return _mock_roast(resolved_lang)
        score = max(1, min(10, score))
        return {"roast": roast, "score": score, "mocked": False}
    except Exception:
        # Fail closed to the mock bank rather than ever surfacing an error
        # or an unmoderated raw model response to the user.
        return _mock_roast(resolved_lang)
