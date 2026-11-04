"""TrustLens API. Run from the backend folder:  uvicorn main:app --port 8000
Open http://localhost:8000 (the backend also serves the frontend)."""
import os, re, io, json, time, base64, sqlite3
from typing import Optional
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))

def load_env():  # tiny .env reader, no extra package needed
    p = os.path.join(HERE, ".env")
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8-sig"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
load_env()

def clean(v):
    v = (v or "").strip()
    return "" if (not v or "your" in v.lower()) else v

GEMINI_KEY = clean(os.getenv("GEMINI_API_KEY"))
ANTHROPIC_KEY = clean(os.getenv("ANTHROPIC_API_KEY"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
ANTHROPIC_MODEL = os.getenv("MODEL", "claude-sonnet-5-5")
PROVIDER = os.getenv("AI_PROVIDER", "").lower() or ("gemini" if GEMINI_KEY else "anthropic" if ANTHROPIC_KEY else "none")
AI_ON = (PROVIDER == "gemini" and bool(GEMINI_KEY)) or (PROVIDER == "anthropic" and bool(ANTHROPIC_KEY))

app = FastAPI(title="TrustLens")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])

DB_PATH = os.path.join(HERE, "trustlens.db")
def db():
    c = sqlite3.connect(DB_PATH)
    c.execute("create table if not exists h(id integer primary key autoincrement, ts real, kind text,"
              " preview text, verdict text, rating int, result text)")
    try: c.execute("alter table h add column client text")
    except sqlite3.OperationalError: pass
    return c

_hits = {}
def limit(cid, per_minute=8):
    now = time.time(); q = [t for t in _hits.get(cid, []) if now - t < 60]
    if len(q) >= per_minute: raise HTTPException(429, "Too many requests. Please wait a minute and try again.")
    _hits[cid] = q + [now]

SENSATIONAL = ["shocking", "you won't believe", "miracle", "secret", "exposed", "they don't want you to know",
               "100% proof", "share before", "banned", "cure", "wake up", "urgent", "bombshell", "hoax", "cover-up",
               "cover up", "sheeple", "deep state", "big pharma", "must watch", "unbelievable", "mind-blowing", "going viral"]
VAGUE = ["experts say", "scientists say", "sources say", "people are saying", "some say", "many believe", "studies show",
         "it is said", "viral post", "reportedly", "allegedly", "insiders"]
ABSOLUTE = ["always", "never", "everyone", "nobody", "100%", "guaranteed", "proven", "all diseases", "prevent all",
            "completely", "totally", "instantly", "overnight"]
ATTRIB = r"according to|\bsaid\b|reported|spokesperson|official|ministry|university|published|journal|data from|statement|press release|court|police|researchers at|study by"
BAD = {"beforeitsnews.com", "infowars.com", "worldnewsdailyreport.com"}
GOOD = {"reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nature.com", "who.int", "thehindu.com", "pib.gov.in"}

def heuristics(text, url=None):
    """Style-and-sourcing score (0-100). It cannot know whether facts are true."""
    t = text.lower(); n = len(re.findall(r"[a-z0-9']+", t))
    score, tone, right, wrong = 55.0, 80.0, [], []
    hits = [w for w in SENSATIONAL if w in t]
    if hits:
        p = min(34, 9 * len(hits)); score -= p; tone -= p
        wrong.append("Sensational or conspiracy wording: " + ", ".join(hits[:4]))
    vague = [w for w in VAGUE if w in t]
    if vague:
        score -= min(14, 6 * len(vague)); wrong.append("Vague sourcing with no named source: " + ", ".join(vague[:3]))
    ab = [w for w in ABSOLUTE if w in t]
    if ab:
        p = min(18, 5 * len(ab)); score -= p; tone -= p; wrong.append("Overly absolute claims: " + ", ".join(ab[:3]))
    letters = [c for c in text if c.isalpha()]
    caps = sum(c.isupper() for c in letters) / len(letters) if letters else 0
    if caps > 0.25: score -= 15; tone -= 20; wrong.append("Excessive capital letters, a common sign of manipulation")
    elif caps > 0.12 and n > 5: score -= 6; tone -= 8; wrong.append("Several words in capital letters")
    ex = text.count("!")
    if ex > 3: score -= 10; tone -= 12; wrong.append("Too many exclamation marks")
    elif ex > 1: score -= 4; tone -= 5
    attr = len(set(re.findall(ATTRIB, t)))
    if attr: score += min(24, 8 * attr); right.append("Attributes information to named sources or officials")
    else: score -= 8; wrong.append("No named sources or attribution")
    sourcing = 20 + 22 * attr - 15 * len(vague)
    nums = set(re.findall(r"\b\d[\d,.]*\s?(?:%|percent|million|billion|thousand)?|\b(?:19|20)\d\d\b", t))
    detail = 25 + 20 * min(len(nums), 3)
    if nums: score += min(10, 4 * len(nums)); right.append("Contains specific, checkable figures or dates")
    if text.count('"') >= 2 or "\u201c" in text: score += 4; right.append("Includes direct quotes")
    if n < 8: score -= 8; wrong.append("Very little text to judge reliably")
    elif n >= 60: score += 5; right.append("Substantial, detailed text")
    if not hits and not ab and caps < 0.12 and ex <= 1 and n >= 15:
        score += 6; tone += 5; right.append("Calm, neutral wording")
    if url:
        d = (urlparse(url).hostname or "").removeprefix("www.")
        if any(d.endswith(g) for g in GOOD): score += 15; right.append(f"{d} is a generally reliable outlet")
        if any(d.endswith(b) for b in BAD): score -= 30; wrong.append(f"{d} is known for misleading content")
        if d.count("-") >= 3 or d.endswith((".xyz", ".click", ".top", ".buzz")): score -= 4; wrong.append("Unusual-looking web address")
    c = lambda v: max(0, min(100, int(round(v))))
    return {"score": c(score), "tone": c(tone), "sourcing": c(sourcing), "detail": c(detail), "right": right, "wrong": wrong}

PROMPT = """You are a careful fact-checking analyst. Analyze the content and reply with ONLY JSON:
{"summary":"2-3 sentence plain summary","core_claim":"the single main claim",
"rating":0-100 credibility (number),"whats_right":["specific things that appear accurate/credible"],
"whats_wrong":["specific errors, unsupported or misleading parts"],"red_flags":["manipulation signs"],
"advice":"how the reader can verify this"}
You cannot browse the web, so judge plausibility, internal consistency, sourcing and manipulation. If the claim is about very recent events you cannot verify, say so and keep the rating moderate.\nBe specific and quote short phrases. If you cannot verify something, say so instead of guessing."""

_gm = {"model": None}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models"

def gemini_models():
    """Ask Google which models this key can use; stable ones first, previews last."""
    r = httpx.get(GEMINI_URL, params={"pageSize": 200}, headers={"x-goog-api-key": GEMINI_KEY}, timeout=20)
    r.raise_for_status()
    bad = ("lite", "image", "tts", "live", "audio", "embed", "robotics", "computer", "exp", "vision", "imagen", "veo", "gemma")
    names = [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    good = [n for n in names if n.startswith("gemini") and not any(b in n for b in bad)]
    pool = [n for n in good if "flash" in n] or good
    return sorted(pool, key=lambda n: ("preview" in n, "latest" in n, [-ord(c) for c in n]))

def gemini_call(model, parts):
    r = httpx.post(f"{GEMINI_URL}/{model}:generateContent", timeout=60, headers={"x-goog-api-key": GEMINI_KEY},
                   json={"contents": [{"parts": parts}],
                         "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}})
    r.raise_for_status()
    ps = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in ps if not p.get("thought"))

RETRY = (400, 404, 429, 500, 502, 503, 504)  # try another model on these (quotas are per model)

def gemini_text(parts):
    cands, tried, discovered, err = [_gm["model"] or GEMINI_MODEL], [], False, None
    while cands:
        m = cands.pop(0)
        if m in tried: continue
        tried.append(m)
        try:
            out = gemini_call(m, parts); _gm["model"] = m
            return out
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in RETRY: raise
            err = e
            if _gm["model"] == m: _gm["model"] = None
            if e.response.status_code >= 500: time.sleep(1.2)
            if not cands and not discovered:
                discovered = True
                cands = [n for n in gemini_models() if n not in tried][:5]
    raise err

def ask_llm(text, image=None):
    prompt = PROMPT + "\n\nCONTENT:\n" + text[:8000]
    if PROVIDER == "gemini":
        parts = [{"text": prompt}]
        if image: parts.append({"inline_data": {"mime_type": image[0], "data": image[1]}})
        s = gemini_text(parts)
    else:
        content = []
        if image: content.append({"type": "image", "source": {"type": "base64", "media_type": image[0], "data": image[1]}})
        content.append({"type": "text", "text": prompt})
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=60,
                       headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": ANTHROPIC_MODEL, "max_tokens": 1200, "messages": [{"role": "user", "content": content}]})
        r.raise_for_status()
        s = r.json()["content"][0]["text"]
    d = json.loads(s[s.find("{"): s.rfind("}") + 1])
    d["rating"] = max(0.0, min(100.0, float(d["rating"])))
    for k in ("whats_right", "whats_wrong", "red_flags"):
        v = d.get(k) or []
        d[k] = [str(x) for x in (v if isinstance(v, list) else [v])]
    return d

def fetch_url(u):
    if not u.startswith("http"): u = "https://" + u
    host = urlparse(u).hostname or ""
    if host in ("localhost", "0.0.0.0") or re.match(r"(127|10|192\.168|169\.254)\.", host):
        raise ValueError("blocked")
    h = httpx.get(u, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 TrustLens"}).text
    h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", "", h)
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", h)
    strip = lambda x: re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", x)).strip()
    paras = [strip(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", h)]
    body = " ".join(p for p in paras if len(p) > 40) or strip(h)
    return u, (m.group(1).strip() if m else ""), body

@app.get("/health")
def health():
    return {"ok": True, "ai": AI_ON, "provider": PROVIDER if AI_ON else "none", "model": _gm["model"] or GEMINI_MODEL}

@app.post("/analyze")
def analyze(text: str = Form(""), url: str = Form(""), file: Optional[UploadFile] = File(None),
            x_client_id: Optional[str] = Header(None)):
    cid = (x_client_id or "anon")[:64]; limit(cid)
    kind, src, image, note, title, fname = "text", text.strip(), None, "", "", ""
    if url.strip():
        kind = "link"
        try:
            url, title, body = fetch_url(url.strip())
        except Exception:
            raise HTTPException(400, "Could not open that link (some sites block bots). Paste the article text instead.")
        src = f"{title}\n{body}"
    if file is not None and file.filename:
        kind, fname = "file", file.filename
        data, ct = file.file.read(), (file.content_type or "")
        if len(data) > 5_000_000: raise HTTPException(413, "File is larger than 5 MB.")
        if ct.startswith("image/"):
            image = (ct, base64.b64encode(data).decode())
        elif ct.startswith("video/"):
            note = "Video frames are not inspected yet; only the caption you added was analyzed."
        elif fname.lower().endswith(".pdf"):
            try:
                from pypdf import PdfReader
                src += "\n" + "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
            except Exception:
                raise HTTPException(400, "Could not read that PDF. Try pasting its text instead.")
        else:
            src += "\n" + data.decode("utf-8", "ignore")
    src = src.strip()
    if len(src) < 12 and not image:
        raise HTTPException(422, "Add a headline, a few sentences, a link, or a file to analyze.")
    if image and not AI_ON:
        raise HTTPException(503, "Image analysis needs an AI key (GEMINI_API_KEY or ANTHROPIC_API_KEY) in backend/.env.")

    h = heuristics(src, url if kind == "link" else None)
    llm = None
    if AI_ON:
        try:
            llm = ask_llm(src or "Analyze this image for misinformation.", image)
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            note += (" AI rate limit reached, wait a minute and retry." if code == 429 else
                     " Google's AI is busy right now, try again in a minute." if code >= 500 else
                     " AI key was rejected: create a new key at aistudio.google.com." if code in (401, 403) else
                     f" AI engine error {code}: the model name may be wrong.")
        except Exception:
            note += " AI engine returned an unreadable answer or was unreachable."
        if llm is None and image:
            raise HTTPException(502, "Image analysis failed." + note)
    if llm is None: note += " Rules-only estimate: it checks writing style and sourcing, not whether the facts are true."
    rating = round(0.7 * llm["rating"] + 0.3 * h["score"]) if llm else h["score"]
    rating = max(0, min(100, int(rating)))
    verdict = "Likely Real" if rating >= 70 else "Uncertain" if rating >= 40 else "Likely Fake"
    first = re.split(r"(?<=[.!?])\s", src)[0][:220] if src else "Image content"
    result = {
        "verdict": verdict, "rating": rating, "stars": round(rating / 20, 1),
        "summary": (llm or {}).get("summary") or (src[:240] + ("..." if len(src) > 240 else "")),
        "core_claim": (llm or {}).get("core_claim") or title or first,
        "right": (llm or {}).get("whats_right", []) + h["right"],
        "wrong": (llm or {}).get("whats_wrong", []) + h["wrong"],
        "red_flags": (llm or {}).get("red_flags", []),
        "advice": (llm or {}).get("advice") or "Search the main claim on Reuters, AP, BBC and a fact-check site.",
        "note": note.strip(), "engine": (PROVIDER.title() + " AI + rules") if llm else "Rules only",
    }
    result["signals"] = ([{"name": "AI fact analysis", "score": int(llm["rating"])}] if llm else []) + [
        {"name": "Tone and wording", "score": h["tone"]}, {"name": "Sourcing", "score": h["sourcing"]},
        {"name": "Specific details", "score": h["detail"]}]
    c = db()
    cur = c.execute("insert into h(ts,kind,preview,verdict,rating,result,client) values(?,?,?,?,?,?,?)",
                    (time.time(), kind, (title or fname or src)[:90], verdict, rating, json.dumps(result), cid))
    c.commit(); result["id"] = cur.lastrowid; c.close()
    return result

@app.get("/history")
def history(x_client_id: Optional[str] = Header(None)):
    c = db()
    rows = c.execute("select id,ts,kind,preview,verdict,rating,result from h where client=? order by id desc limit 50",
                     ((x_client_id or "anon")[:64],)).fetchall()
    c.close()
    return [{"id": r[0], "ts": r[1], "kind": r[2], "preview": r[3], "verdict": r[4], "rating": r[5],
             "result": json.loads(r[6])} for r in rows]

@app.delete("/history")
def clear_history(x_client_id: Optional[str] = Header(None)):
    c = db(); c.execute("delete from h where client=?", ((x_client_id or "anon")[:64],)); c.commit(); c.close()
    return {"ok": True}

FRONT = os.path.join(HERE, "..", "frontend")  # must stay LAST so API routes win
if os.path.isdir(FRONT):
    app.mount("/", StaticFiles(directory=FRONT, html=True), name="web")
