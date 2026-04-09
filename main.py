"""
Telecaller Training API — FastAPI Backend
Deploy on Railway/Render/Fly.io (NOT Vercel — needs persistent audio processing)

pip install fastapi uvicorn python-multipart anthropic groq cartesia requests numpy soundfile scipy
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

# For phone line audio effects
try:
    from scipy import signal
    from scipy.io import wavfile
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

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
            "- Keep replies conversational (typically 5-15 words). Vary your length naturally.\n"
            "- Sometimes be brief (3-5 words), sometimes more elaborate (10-15 words).\n"
            "- NO asterisks, NO narration, NO stage directions.\n"
            "- Opening: 'Yeah?' or 'Hello, who's this?' or 'Robert Chen speaking.'\n"
            "- When they pitch: 'Okay, what exactly are you selling?' or 'I'm kind of in the middle of something here.'\n"
            "- If vague/long-winded: 'Can you just get to the point? I don't have a lot of time.'\n"
            "- If they make sense, respond with realistic questions or concerns.\n"
            "- American English. Sound like a real busy professional on the phone.\n"
            "- Use natural speech patterns: 'uh', 'hmm', 'well', 'I mean', occasionally.\n"
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
            "- Vary your responses (5-12 words typically). You're distracted.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Hello?' or 'Yeah, who is this?'\n"
            "- If they take too long: 'Sorry, what company did you say this was?'\n"
            "- Show distraction: 'Hold on— sorry, what were you saying?'\n"
            "- To end: 'You know what, I really can't talk right now' then stop.\n"
            "- Use filler words naturally: 'um', 'uh', 'like', 'sorry'.\n"
            "- Sound harried and multitasking.\n"
        )
    },
    {
        "id": "price_hawk",
        "name": "Mike Thompson",
        "gender": "male",
        "description": "Blunt 40-year-old, everything is about the price",
        "system_prompt": (
            "You are Mike. You only care about price and value.\n\n"
            "ABSOLUTE RULES:\n"
            "- Output ONLY what you say aloud. Nothing else.\n"
            "- Mix short and medium responses (4-12 words). Be direct but not robotic.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Yeah, what's this about?'\n"
            "- First real question: 'Okay, so how much are we talking per month?'\n"
            "- If they dodge price: 'Yeah but what's the actual monthly cost? Just give me a number.'\n"
            "- Compare bluntly: 'I've seen better rates online. Why should I go with you?'\n"
            "- Use natural emphasis: 'Look', 'Listen', 'Here's the thing'.\n"
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
            "- Longer responses are okay (8-18 words). You process slowly.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Hello? Who's calling please?' or 'Yes, this is Dorothy.'\n"
            "- Mishear: 'I'm sorry dear, could you repeat that?' or 'Come again, honey? I didn't quite catch that.'\n"
            "- Decisions need family: 'Oh, I'd really need to talk to my son about something like that.'\n"
            "- Warm Southern American English. Use 'dear', 'honey', 'oh my'.\n"
            "- Sound genuinely sweet but confused.\n"
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
            "- Short to medium (4-10 words). You don't waste time.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Yeah, who is this?' or 'What do you want?'\n"
            "- Long intro: 'Is this a sales call? Because I'm not interested.'\n"
            "- Direct challenge: 'Look, I'm on the Do Not Call list. How'd you get this number?'\n"
            "- If not clear fast: 'Not interested. Don't call again.' Then stop.\n"
            "- Gruff but realistic. Use 'Look', 'Listen pal'.\n"
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
            "- Conversational length (6-15 words). Sound smart and aware.\n"
            "- NO asterisks, NO narration.\n"
            "- Opening: 'Hello?' or 'Yeah, hi, who's this?'\n"
            "- Sense a script: 'Wait, sorry— are you reading from a script right now?'\n"
            "- If robotic: 'Okay, I'm gonna be honest, this sounds really rehearsed.'\n"
            "- If genuine: Ask thoughtful questions. Be engaged but skeptical.\n"
            "- Use casual speech: 'like', 'honestly', 'I mean', 'wait'.\n"
        )
    },
]

DIFFICULTY_CONFIGS = {
    "beginner":     {"label": "Beginner",     "emoji": "🟢", "guidance": "Be cooperative and friendly. Raise only 1 soft concern then warm up quickly. Give them hints about what to say next. Keep responses encouraging."},
    "intermediate": {"label": "Intermediate", "emoji": "🟡", "guidance": "Be moderately skeptical. Raise 2-3 realistic objections. Make them work for it but be fair. Respond naturally to good handling."},
    "advanced":     {"label": "Advanced",     "emoji": "🔴", "guidance": "Be very difficult. Multiple strong objections. Interrupt if they ramble. Only excellent technique moves you forward. Push back hard."},
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
    allow_origins=["*"],
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
# PHONE LINE AUDIO EFFECTS
# ══════════════════════════════════════════════════════════════════════

def add_phone_line_effects(audio_bytes: bytes, sample_rate: int = 22050) -> bytes:
    if not SCIPY_AVAILABLE:
        return audio_bytes
    try:
        audio_io = io.BytesIO(audio_bytes)
        rate, data = wavfile.read(audio_io)
        if data.dtype == np.int16:
            audio_float = data.astype(np.float32) / 32768.0
        else:
            audio_float = data.astype(np.float32)
        nyquist = rate / 2
        low = 300 / nyquist
        high = 3400 / nyquist
        b, a = signal.butter(4, [low, high], btype='band')
        filtered = signal.filtfilt(b, a, audio_float)
        noise_level = 0.002
        noise = np.random.normal(0, noise_level, len(filtered))
        with_noise = filtered + noise
        if random.random() < 0.3:
            crackle_positions = np.random.choice(len(with_noise), size=int(len(with_noise) * 0.001), replace=False)
            for pos in crackle_positions:
                if pos < len(with_noise):
                    with_noise[pos] += random.uniform(-0.01, 0.01)
        threshold = 0.3
        ratio = 3.0
        compressed = np.where(
            np.abs(with_noise) > threshold,
            np.sign(with_noise) * (threshold + (np.abs(with_noise) - threshold) / ratio),
            with_noise
        )
        max_val = np.max(np.abs(compressed))
        if max_val > 0:
            compressed = compressed * 0.95 / max_val
        audio_int16 = (compressed * 32767).astype(np.int16)
        output_io = io.BytesIO()
        wavfile.write(output_io, rate, audio_int16)
        return output_io.getvalue()
    except Exception as e:
        print(f"Phone effect error: {e}")
        return audio_bytes

# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def detect_audio_extension(audio_bytes: bytes, content_type: str) -> str:
    """
    Detect the real audio format from magic bytes or content-type.
    Returns the correct file extension so Whisper can decode it.
    """
    # Check magic bytes first (most reliable)
    if audio_bytes[:4] == b'RIFF':
        return '.wav'
    if audio_bytes[:4] == b'fLaC':
        return '.flac'
    if audio_bytes[:3] == b'ID3' or audio_bytes[:2] == b'\xff\xfb':
        return '.mp3'
    if audio_bytes[:4] == b'OggS':
        return '.ogg'
    # WebM/MKV magic bytes
    if audio_bytes[:4] == b'\x1a\x45\xdf\xa3':
        return '.webm'
    # MP4/M4A (ftyp box)
    if len(audio_bytes) > 8 and audio_bytes[4:8] in (b'ftyp', b'moov', b'mdat'):
        return '.mp4'

    # Fall back to content-type
    ct = (content_type or '').lower()
    if 'webm' in ct:
        return '.webm'
    if 'ogg' in ct:
        return '.ogg'
    if 'mp4' in ct or 'm4a' in ct:
        return '.mp4'
    if 'mp3' in ct or 'mpeg' in ct:
        return '.mp3'
    if 'flac' in ct:
        return '.flac'
    if 'wav' in ct:
        return '.wav'

    # Default: treat as webm (most common from Chrome/Firefox MediaRecorder)
    return '.webm'


def transcribe_audio(audio_bytes: bytes, content_type: str) -> str:
    """
    Transcribe audio bytes → text using Whisper.
    Detects actual format and writes with correct extension so ffmpeg decodes correctly.
    """
    model = get_whisper()
    ext = detect_audio_extension(audio_bytes, content_type)

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        if _whisper_backend == "faster_whisper":
            segments, info = model.transcribe(
                tmp_path,
                language="en",
                beam_size=3,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300}
            )
            text = " ".join(s.text.strip() for s in segments).strip()
        else:
            result = model.transcribe(tmp_path, language="en", fp16=False)
            text = result["text"].strip()
        return text
    except Exception as e:
        # If local whisper fails, try Groq Whisper API as fallback
        print(f"Local whisper error: {e}, trying Groq Whisper API...")
        return transcribe_via_groq(audio_bytes, ext)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def transcribe_via_groq(audio_bytes: bytes, ext: str) -> str:
    """
    Fallback transcription via Groq's Whisper API endpoint.
    This handles webm/mp4 reliably without needing local ffmpeg.
    """
    filename = f"audio{ext}"
    mime_map = {
        '.webm': 'audio/webm',
        '.mp4':  'audio/mp4',
        '.ogg':  'audio/ogg',
        '.mp3':  'audio/mpeg',
        '.wav':  'audio/wav',
        '.flac': 'audio/flac',
        '.m4a':  'audio/mp4',
    }
    mime = mime_map.get(ext, 'audio/webm')

    try:
        r = requests.post(
            f"{GROQ_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": (filename, io.BytesIO(audio_bytes), mime)},
            data={"model": "whisper-large-v3-turbo", "language": "en", "response_format": "text"},
            timeout=30,
        )
        r.raise_for_status()
        # response_format=text returns plain text, not JSON
        result = r.text.strip()
        return result
    except Exception as e:
        raise RuntimeError(f"Groq transcription also failed: {e}")


def synthesize_speech(text: str, voice_id: str, add_phone_effects: bool = True) -> bytes:
    """Synthesize text → WAV bytes via Cartesia with optional phone line effects."""
    payload = {
        "model_id":   CARTESIA_MODEL,
        "transcript": text,
        "voice":      {
            "mode": "id",
            "id": voice_id,
            "__experimental_controls": {
                "speed": "normal",
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
    audio_bytes = r.content
    if add_phone_effects:
        audio_bytes = add_phone_line_effects(audio_bytes, PLAYBACK_RATE)
    return audio_bytes


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
        "Stay in character AT ALL TIMES. You are a REAL person on the phone. "
        "Respond ONLY with what you would say. Be conversational - not too short, not too long. "
        "Vary your response length naturally based on the situation. "
        "Never reveal you are an AI or that this is training."
    )

    history.append({"role": "user", "content": caller_text})
    messages = [{"role": "system", "content": system}] + history

    r = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": GROQ_MODEL, "max_tokens": 300, "temperature": 0.8, "messages": messages},
        timeout=20,
    )
    r.raise_for_status()
    reply = r.json()["choices"][0]["message"]["content"].strip()
    reply = reply.replace('*', '').replace('[', '').replace(']', '')
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
    # Strip any markdown code fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    # Strip trailing ``` if present
    if raw.endswith("```"):
        raw = raw[:-3].strip()
    return json.loads(raw)

# ══════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {"status": "ok", "service": "Telecaller Training API", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/profiles")
def get_profiles():
    return [{"id": p["id"], "name": p["name"], "description": p["description"], "gender": p["gender"]} for p in CUSTOMER_PROFILES]

@app.get("/difficulties")
def get_difficulties():
    return [{"id": k, "label": v["label"], "emoji": v["emoji"]} for k, v in DIFFICULTY_CONFIGS.items()]


# ── Session management ─────────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    profile_id: str
    difficulty: str = "intermediate"

@app.post("/session/create")
def create_session(req: SessionCreateRequest):
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
        "history":     [],
        "transcript":  [],
        "started_at":  time.time(),
        "status":      "active",
    }
    SESSIONS[session_id] = session

    greeting = ai_customer_respond(
        session,
        "[system] You just picked up the phone. Unknown number. Say what you would actually say when picking up. Be natural and conversational."
    )
    session["transcript"].append({
        "role": "customer", "text": greeting, "timestamp": time.time()
    })

    try:
        audio_bytes = synthesize_speech(greeting, voice_id, add_phone_effects=True)
        audio_b64 = __import__("base64").b64encode(audio_bytes).decode()
    except Exception as e:
        audio_b64 = None

    return {
        "session_id":         session_id,
        "profile":            {"id": profile["id"], "name": profile["name"], "description": profile["description"]},
        "difficulty":         req.difficulty,
        "voice_id":           voice_id,
        "greeting_text":      greeting,
        "greeting_audio_b64": audio_b64,
        "audio_sample_rate":  PLAYBACK_RATE,
    }


@app.get("/session/{session_id}")
def get_session(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    return {
        "session_id":    session_id,
        "status":        session["status"],
        "profile":       session["profile"]["name"],
        "difficulty":    session["difficulty"],
        "turns":         len([t for t in session["transcript"] if t["role"] == "telecaller"]),
        "transcript":    session["transcript"],
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
    Supports webm, mp4, ogg, wav, mp3, flac — auto-detected from magic bytes.
    """
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")
    if session["status"] == "ended":
        raise HTTPException(400, "Session has already ended.")

    audio_bytes = await audio.read()

    if len(audio_bytes) < 500:
        return {
            "transcription": "",
            "response_text": None,
            "response_audio_b64": None,
            "session_ended": False,
            "note": "Audio too short or empty"
        }

    # 1. Transcribe — detects format automatically
    try:
        caller_text = transcribe_audio(audio_bytes, audio.content_type or "")
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {e}")

    if not caller_text.strip():
        return {
            "transcription": "",
            "response_text": None,
            "response_audio_b64": None,
            "session_ended": False,
            "note": "No speech detected"
        }

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
        audio_bytes_out = synthesize_speech(response_text, session["voice_id"], add_phone_effects=True)
        response_audio_b64 = __import__("base64").b64encode(audio_bytes_out).decode()
    except Exception:
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


# ── Text-only turn ─────────────────────────────────────────────────────

class TextTurnRequest(BaseModel):
    text: str

@app.post("/session/{session_id}/turn/text")
def session_turn_text(session_id: str, req: TextTurnRequest):
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
        audio_bytes = synthesize_speech(response_text, session["voice_id"], add_phone_effects=True)
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
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found.")

    session["status"] = "ended"

    try:
        result = evaluate_session(session)
    except Exception as e:
        raise HTTPException(500, f"Evaluation failed: {e}")

    return {
        "session_id":    session_id,
        "customer":      session["profile"]["name"],
        "difficulty":    session["difficulty"],
        "duration_secs": round(time.time() - session["started_at"], 1),
        "total_turns":   len([t for t in session["transcript"] if t["role"] == "telecaller"]),
        "transcript":    session["transcript"],
        "evaluation":    result,
    }


@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    if session_id in SESSIONS:
        del SESSIONS[session_id]
    return {"deleted": True}


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════
from fastapi.responses import FileResponse

@app.get("/")
async def serve_ui():
    return FileResponse("telecaller_trainer.html")
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
