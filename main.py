"""
Telecaller Training API — FastAPI Backend
Deploy on Railway/Render/Fly.io (NOT Vercel — needs persistent audio processing)

pip install fastapi uvicorn python-multipart anthropic groq cartesia requests numpy soundfile
"""

import os
import io
import json
import uuid
import time
import random
import tempfile
from datetime import datetime
from typing import Optional
from pathlib import Path

import numpy as np
import requests
from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel


# ── optional faster-whisper ────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
    _whisper_backend = "faster_whisper"
except ImportError:
    import whisper as openai_whisper
    _whisper_backend = "openai_whisper"

# ══════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════

GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "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")
CARTESIA_API_KEY  = os.getenv("CARTESIA_API_KEY", "sk_car_c77D8tBJjLttDgy9aSiasX")
CARTESIA_VERSION  = "2024-06-10"
CARTESIA_BASE_URL = "https://api.cartesia.ai"
CARTESIA_MODEL    = "sonic-english"
GROQ_BASE_URL     = "https://api.groq.com/openai/v1"
GROQ_MODEL        = "llama-3.3-70b-versatile"
PLAYBACK_RATE     = 22050

# In-memory session store (use Redis in prod)
SESSIONS: dict[str, dict] = {}

# ══════════════════════════════════════════════════════════════════════
# CUSTOMER PROFILES
# ══════════════════════════════════════════════════════════════════════

CUSTOMER_PROFILES = [
    {
        "id": "skeptical_businessman",
        "name": "Robert Chen",
        "gender": "male",
        "description": "Skeptical 46-year-old, guarded on cold calls",
        "system_prompt": (
            "You are Robert, a real person who just got a cold call you weren't expecting.\n\n"
            "ABSOLUTE RULES:\n"
            "- Output ONLY the words you speak aloud. Nothing else.\n"
            "- Keep replies SHORT (3-10 words). Real phone replies aren't speeches.\n"
            "- NO asterisks, NO narration, NO stage directions.\n"
            "- Opening: 'Yeah?' or 'Hello?' or 'Who's this?'\n"
            "- When they pitch: 'What are you selling?' Cut in.\n"
            "- If vague/long-winded, interrupt: 'Just get to the point.'\n"
            "- If they make sense, ask one short question. One.\n"
            "- American English. No filler compliments.\n"
        )
    },
    {
        "id": "busy_working_mom",
        "name": "Sarah Johnson",
        "gender": "female",
        "description": "Distracted 34-year-old, already half-checked out",
        "system_prompt": (
            "You are Sarah, busy person who picked up an unknown number by mistake.\n\n"
            "ABSOLUTE RULES:\n"
            "- Output ONLY what you say aloud. Nothing else.\n"
            "- One sentence or less. You're busy.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Hello?' or 'Yeah, who's this?'\n"
            "- If they take too long: 'Okay what are you selling?'\n"
            "- Trail off: 'Sorry— what?'\n"
            "- To hang up: 'okay I gotta go' then stop.\n"
        )
    },
    {
        "id": "price_hawk",
        "name": "Mike Thompson",
        "gender": "male",
        "description": "Blunt 40-year-old, everything is about the price",
        "system_prompt": (
            "You are Mike. You only care about price.\n\n"
            "ABSOLUTE RULES:\n"
            "- Output ONLY what you say aloud. Nothing else.\n"
            "- SHORT. You interrogate.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Yeah?'\n"
            "- First real question: 'How much?' Two words.\n"
            "- If they dodge price: 'Okay but what's the monthly?'\n"
            "- Compare bluntly: 'I got a lower quote somewhere else.'\n"
        )
    },
    {
        "id": "confused_retiree",
        "name": "Dorothy Williams",
        "gender": "female",
        "description": "Elderly 69-year-old, mishears things, needs repetition",
        "system_prompt": (
            "You are Dorothy, an elderly woman who picked up unsure who was calling.\n\n"
            "ABSOLUTE RULES:\n"
            "- Output ONLY what you say aloud. Nothing else.\n"
            "- SHORT and natural. No speeches.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Hello?' or 'Who's calling please?'\n"
            "- Mishear: 'Sorry, what was that?' or 'Come again, honey?'\n"
            "- Decisions need family: 'I'd have to talk to my son about that.'\n"
            "- Warm Southern American English. Slow.\n"
        )
    },
    {
        "id": "demanding_guy",
        "name": "James Miller",
        "gender": "male",
        "description": "Blunt 52-year-old, zero patience, already suspicious",
        "system_prompt": (
            "You are James, already suspicious it's a sales call.\n\n"
            "ABSOLUTE RULES:\n"
            "- Output ONLY what you say aloud. Nothing else.\n"
            "- SHORT. You don't chat.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Yeah.' or 'Who's this?'\n"
            "- Long intro: 'What do you want?'\n"
            "- Direct question: 'Is this a sales call?'\n"
            "- If not clear fast: 'Not interested.' Then stop.\n"
        )
    },
    {
        "id": "millennial_professional",
        "name": "Emily Davis",
        "gender": "female",
        "description": "29-year-old, curious but clocks scripted pitches instantly",
        "system_prompt": (
            "You are Emily, picked up an unknown number on a whim.\n\n"
            "ABSOLUTE RULES:\n"
            "- Output ONLY what you say aloud. Nothing else.\n"
            "- SHORT and conversational. One or two sentences max.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Hello?' or 'Yeah, hi?'\n"
            "- Sense a script: 'Wait, is this a sales thing?'\n"
            "- Robotic: 'Are you reading off something right now?'\n"
            "- If genuine, ask a real short question back.\n"
        )
    },
]

DIFFICULTY_CONFIGS = {
    "beginner":     {"label": "Beginner",     "emoji": "🟢", "guidance": "Be cooperative. Raise only 1 soft objection then warm up. Hint toward what they should say."},
    "intermediate": {"label": "Intermediate", "emoji": "🟡", "guidance": "Be moderately skeptical. Raise 2-3 realistic objections. Make them work for the sale."},
    "advanced":     {"label": "Advanced",     "emoji": "🔴", "guidance": "Be very difficult. Multiple strong objections. Only excellent pitches move you."},
}

EVALUATION_RUBRIC = {
    "fluency":                "Smooth, uninterrupted speech. No excessive filler words.",
    "pronunciation":          "Clear, accurate pronunciation including insurance terms.",
    "american_english_accent":"Consistency and clarity of American English accent.",
    "professionalism":        "Polished, courteous tone. Avoided slang.",
    "active_listening":       "Addressed customer's specific points. Didn't ignore concerns.",
    "product_knowledge":      "Demonstrated accurate knowledge of insurance products.",
    "objection_handling":     "Addressed objections with empathy then pivoted positively.",
    "closing_ability":        "Moved toward commitment naturally without being pushy.",
    "empathy":                "Acknowledged customer's perspective genuinely.",
    "confidence":             "Maintained composure under pressure. Firm but not aggressive.",
}

# ══════════════════════════════════════════════════════════════════════
# APP SETUP
# ══════════════════════════════════════════════════════════════════════

app = FastAPI(title="Telecaller Training API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict to your domain in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── lazy-loaded whisper ────────────────────────────────────────────────
_whisper_model = None

def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        if _whisper_backend == "faster_whisper":
            _whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
        else:
            _whisper_model = openai_whisper.load_model("base.en")
    return _whisper_model

# ── TTS voices cache ───────────────────────────────────────────────────
_tts_voices: dict[str, list[str]] = {"male": [], "female": []}
_voices_loaded = False

def load_tts_voices():
    global _tts_voices, _voices_loaded
    if _voices_loaded:
        return
    try:
        r = requests.get(
            f"{CARTESIA_BASE_URL}/voices",
            headers={"X-API-Key": CARTESIA_API_KEY, "Cartesia-Version": CARTESIA_VERSION},
            timeout=10,
        )
        r.raise_for_status()
        voices = r.json()
        for v in voices:
            lang = (v.get("language") or "").lower()
            if lang and "en" not in lang:
                continue
            desc = (str(v.get("description", "")) + (v.get("name") or "")).lower()
            vid = v.get("id", "")
            if any(w in desc for w in ["woman", "female", "girl", "lady"]):
                _tts_voices["female"].append(vid)
            elif any(w in desc for w in ["man", "male", "guy", "gentleman"]):
                _tts_voices["male"].append(vid)
            else:
                _tts_voices["male"].append(vid)
                _tts_voices["female"].append(vid)
        _voices_loaded = True
    except Exception:
        _tts_voices = {
            "male":   ["a0e99841-438c-4a64-b679-ae501e7d6091"],
            "female": ["79a125e8-cd45-4c13-8a67-188112f4dd22"],
        }
        _voices_loaded = True

def pick_voice(gender: str) -> str:
    load_tts_voices()
    pool = _tts_voices.get(gender, []) or _tts_voices["male"]
    return random.choice(pool) if pool else "a0e99841-438c-4a64-b679-ae501e7d6091"

# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def transcribe_audio(audio_bytes: bytes, content_type: str) -> str:
    """Transcribe audio bytes → text using Whisper."""
    model = get_whisper()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        if _whisper_backend == "faster_whisper":
            segments, _ = model.transcribe(tmp_path, language="en", beam_size=3, vad_filter=True)
            return " ".join(s.text.strip() for s in segments).strip()
        else:
            result = model.transcribe(tmp_path, language="en", fp16=False)
            return result["text"].strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def synthesize_speech(text: str, voice_id: str) -> bytes:
    """Synthesize text → WAV bytes via Cartesia."""
    payload = {
        "model_id":   CARTESIA_MODEL,
        "transcript": text,
        "voice":      {
            "mode": "id", 
            "id": voice_id,
            "__experimental_controls": {
                "speed": "slow",      # Options: "slowest", "slow", "normal", "fast", "fastest"
                "emotion": []
            }
        },
        "output_format": {
            "container":   "wav",
            "encoding":    "pcm_s16le",
            "sample_rate": PLAYBACK_RATE,
        },
    }
    r = requests.post(
        f"{CARTESIA_BASE_URL}/tts/bytes",
        headers={
            "X-API-Key":        CARTESIA_API_KEY,
            "Cartesia-Version": CARTESIA_VERSION,
            "Content-Type":     "application/json",
        },
        json=payload,
        timeout=20,
    )
    r.raise_for_status()
    return r.content


def ai_customer_respond(session: dict, caller_text: str) -> str:
    """Get AI customer response via Groq."""
    profile    = session["profile"]
    difficulty = session["difficulty"]
    history    = session["history"]
    diff_conf  = DIFFICULTY_CONFIGS[difficulty]

    system = (
        f"{profile['system_prompt']}\n\n"
        f"=== DIFFICULTY: {diff_conf['label'].upper()} ===\n"
        f"{diff_conf['guidance']}\n\n"
        "Stay in character AT ALL TIMES. You are a REAL person. "
        "Respond ONLY with what you would say. SHORT. 1-3 sentences max. "
        "Never reveal you are an AI or that this is training."
    )

    history.append({"role": "user", "content": caller_text})
    messages = [{"role": "system", "content": system}] + history

    r = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": GROQ_MODEL, "max_tokens": 200, "messages": messages},
        timeout=20,
    )
    r.raise_for_status()
    reply = r.json()["choices"][0]["message"]["content"].strip()
    history.append({"role": "assistant", "content": reply})
    return reply


def evaluate_session(session: dict) -> dict:
    """Run evaluation on completed session transcript."""
    transcript  = session["transcript"]
    profile     = session["profile"]
    difficulty  = session["difficulty"]
    duration    = time.time() - session["started_at"]

    if not transcript:
        return {"error": "No transcript to evaluate."}

    rubric_lines = "\n".join(f"  {k}: {v}" for k, v in EVALUATION_RUBRIC.items())
    transcript_text = "\n".join(
        f"{'[TELECALLER]' if t['role'] == 'telecaller' else '[CUSTOMER]'}: {t['text']}"
        for t in transcript
    )

    prompt = f"""You are an expert telecaller trainer evaluating an insurance sales call simulation.

CUSTOMER: {profile['name']} — {profile['description']}
DIFFICULTY: {difficulty.upper()}
DURATION: {int(duration // 60)}m {int(duration % 60)}s
TURNS: {len([t for t in transcript if t['role'] == 'telecaller'])} (telecaller turns)

TRANSCRIPT:
{transcript_text}

EVALUATION CRITERIA (score each 1–10):
{rubric_lines}

INSTRUCTIONS:
1. Score each criterion 1-10. Be STRICT — 8+ means genuinely excellent.
2. Provide 1-2 sentence feedback per criterion.
3. Identify the 3 strongest moments (with quotes if possible).
4. Identify 3 biggest improvement areas with specific suggestions.
5. Give an overall summary (3-4 sentences).
6. Overall score = weighted average.

Respond ONLY with valid JSON:
{{
  "scores": {{
    "fluency": {{"score": 0, "feedback": ""}},
    "pronunciation": {{"score": 0, "feedback": ""}},
    "american_english_accent": {{"score": 0, "feedback": ""}},
    "professionalism": {{"score": 0, "feedback": ""}},
    "active_listening": {{"score": 0, "feedback": ""}},
    "product_knowledge": {{"score": 0, "feedback": ""}},
    "objection_handling": {{"score": 0, "feedback": ""}},
    "closing_ability": {{"score": 0, "feedback": ""}},
    "empathy": {{"score": 0, "feedback": ""}},
    "confidence": {{"score": 0, "feedback": ""}}
  }},
  "strongest_moments": ["", "", ""],
  "improvement_areas": [
    {{"area": "", "suggestion": ""}},
    {{"area": "", "suggestion": ""}},
    {{"area": "", "suggestion": ""}}
  ],
  "overall_score": 0.0,
  "summary": "",
  "grade": ""
}}"""

    r = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": GROQ_MODEL,
            "max_tokens": 2000,
            "messages": [
                {"role": "system", "content": "You are an expert telecaller trainer. Respond ONLY with valid JSON. No markdown, no explanation outside JSON."},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=60,
    )
    r.raise_for_status()
    raw = r.json()["choices"][0]["message"]["content"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)

# ══════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════

# ── Health ─────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "Telecaller Training API", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ── Config endpoints ────────────────────────────────────────────────────

@app.get("/profiles")
def get_profiles():
    """List all customer personality profiles."""
    return [{"id": p["id"], "name": p["name"], "description": p["description"], "gender": p["gender"]} for p in CUSTOMER_PROFILES]

@app.get("/difficulties")
def get_difficulties():
    """List difficulty levels."""
    return [{"id": k, "label": v["label"], "emoji": v["emoji"]} for k, v in DIFFICULTY_CONFIGS.items()]


# ── Session management ─────────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    profile_id: str
    difficulty: str = "intermediate"

@app.post("/session/create")
def create_session(req: SessionCreateRequest):
    """Create a new training session. Returns session_id + opening audio."""
    profile = next((p for p in CUSTOMER_PROFILES if p["id"] == req.profile_id), None)
    if not profile:
        raise HTTPException(404, f"Profile '{req.profile_id}' not found.")
    if req.difficulty not in DIFFICULTY_CONFIGS:
        raise HTTPException(400, f"Invalid difficulty. Choose: {list(DIFFICULTY_CONFIGS.keys())}")

    session_id = str(uuid.uuid4())
    voice_id   = pick_voice(profile["gender"])

    session = {
        "id":          session_id,
        "profile":     profile,
        "difficulty":  req.difficulty,
        "voice_id":    voice_id,
        "history":     [],           # AI customer convo history
        "transcript":  [],           # full transcript [{role, text, timestamp}]
        "started_at":  time.time(),
        "status":      "active",     # active | ended
    }
    SESSIONS[session_id] = session

    # Get opening greeting from AI customer
    greeting = ai_customer_respond(
        session,
        "[system] You just picked up the phone. Unknown number. Say only what you would actually say when picking up. One or two words max."
    )
    session["transcript"].append({
        "role": "customer", "text": greeting, "timestamp": time.time()
    })

    # Synthesize opening audio
    try:
        audio_bytes = synthesize_speech(greeting, voice_id)
        audio_b64 = __import__("base64").b64encode(audio_bytes).decode()
    except Exception as e:
        audio_b64 = None

    return {
        "session_id":   session_id,
        "profile":      {"id": profile["id"], "name": profile["name"], "description": profile["description"]},
        "difficulty":   req.difficulty,
        "voice_id":     voice_id,
        "greeting_text": greeting,
        "greeting_audio_b64": audio_b64,   # WAV base64
        "audio_sample_rate": PLAYBACK_RATE,
    }


@app.get("/session/{session_id}")
def get_session(session_id: str):
    """Get session status and transcript."""
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    return {
        "session_id":  session_id,
        "status":      session["status"],
        "profile":     session["profile"]["name"],
        "difficulty":  session["difficulty"],
        "turns":       len([t for t in session["transcript"] if t["role"] == "telecaller"]),
        "transcript":  session["transcript"],
        "duration_secs": round(time.time() - session["started_at"], 1),
    }


# ── Main turn: audio in → text + audio out ─────────────────────────────

@app.post("/session/{session_id}/turn")
async def session_turn(
    session_id: str,
    audio: UploadFile = File(...),
):
    """
    Send telecaller audio → get customer response audio + text back.
    
    Upload: multipart/form-data with 'audio' field (WAV/WebM/MP3/etc)
    Returns JSON with:
      - transcription: what telecaller said
      - response_text: what customer said
      - response_audio_b64: WAV base64
      - session_ended: bool (if end-of-call detected)
    """
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    if session["status"] == "ended":
        raise HTTPException(400, "Session has already ended. Call /session/{id}/evaluate to get results.")

    audio_bytes = await audio.read()

    # 1. Transcribe telecaller audio
    try:
        caller_text = transcribe_audio(audio_bytes, audio.content_type or "audio/wav")
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {e}")

    if not caller_text.strip():
        return {"transcription": "", "response_text": None, "response_audio_b64": None, "session_ended": False, "note": "No speech detected"}

    session["transcript"].append({
        "role": "telecaller", "text": caller_text, "timestamp": time.time()
    })

    # 2. Check for end-of-call phrases
    END_PHRASES = {"goodbye", "end call", "hang up", "bye bye", "thank you bye", "thanks bye", "that will be all"}
    session_ended = any(ep in caller_text.lower() for ep in END_PHRASES)

    # 3. Get AI customer response
    try:
        response_text = ai_customer_respond(session, caller_text)
    except Exception as e:
        raise HTTPException(500, f"AI response failed: {e}")

    session["transcript"].append({
        "role": "customer", "text": response_text, "timestamp": time.time()
    })

    # 4. Synthesize response audio
    try:
        audio_bytes_out = synthesize_speech(response_text, session["voice_id"])
        response_audio_b64 = __import__("base64").b64encode(audio_bytes_out).decode()
    except Exception as e:
        response_audio_b64 = None

    if session_ended:
        session["status"] = "ended"

    return {
        "transcription":       caller_text,
        "response_text":       response_text,
        "response_audio_b64":  response_audio_b64,
        "audio_sample_rate":   PLAYBACK_RATE,
        "session_ended":       session_ended,
        "turn_number":         len([t for t in session["transcript"] if t["role"] == "telecaller"]),
    }


# ── Text-only turn (no audio hardware needed) ──────────────────────────

class TextTurnRequest(BaseModel):
    text: str

@app.post("/session/{session_id}/turn/text")
def session_turn_text(session_id: str, req: TextTurnRequest):
    """
    Text-only turn — send telecaller text, get customer text + audio back.
    Useful for testing or when browser mic is unavailable.
    """
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    if session["status"] == "ended":
        raise HTTPException(400, "Session already ended.")

    caller_text = req.text.strip()
    if not caller_text:
        raise HTTPException(400, "Text cannot be empty.")

    session["transcript"].append({
        "role": "telecaller", "text": caller_text, "timestamp": time.time()
    })

    END_PHRASES = {"goodbye", "end call", "hang up", "bye bye", "thank you bye", "thanks bye"}
    session_ended = any(ep in caller_text.lower() for ep in END_PHRASES)

    response_text = ai_customer_respond(session, caller_text)
    session["transcript"].append({
        "role": "customer", "text": response_text, "timestamp": time.time()
    })

    try:
        audio_bytes = synthesize_speech(response_text, session["voice_id"])
        response_audio_b64 = __import__("base64").b64encode(audio_bytes).decode()
    except Exception:
        response_audio_b64 = None

    if session_ended:
        session["status"] = "ended"

    return {
        "transcription":      caller_text,
        "response_text":      response_text,
        "response_audio_b64": response_audio_b64,
        "audio_sample_rate":  PLAYBACK_RATE,
        "session_ended":      session_ended,
    }


# ── Evaluate ───────────────────────────────────────────────────────────

@app.post("/session/{session_id}/evaluate")
def evaluate(session_id: str):
    """
    End session and return detailed performance evaluation.
    Can be called at any time — will also mark session as ended.
    """
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    session["status"] = "ended"

    try:
        result = evaluate_session(session)
    except Exception as e:
        raise HTTPException(500, f"Evaluation failed: {e}")

    return {
        "session_id":      session_id,
        "customer":        session["profile"]["name"],
        "difficulty":      session["difficulty"],
        "duration_secs":   round(time.time() - session["started_at"], 1),
        "total_turns":     len([t for t in session["transcript"] if t["role"] == "telecaller"]),
        "transcript":      session["transcript"],
        "evaluation":      result,
    }


@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    """Clean up a session from memory."""
    if session_id in SESSIONS:
        del SESSIONS[session_id]
    return {"deleted": True}


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
