# Telecaller Training API — Deployment Guide

## Architecture

```
React App (Vercel/Netlify)
       ↕  REST API
FastAPI Backend (Railway/Render/Fly.io)
       ↕              ↕              ↕
  Groq (STT AI)   Cartesia (TTS)  Whisper (local)
```

> ⚠️ The **backend CANNOT run on Vercel** — it needs persistent processes for Whisper
> and long-running audio requests. Use Railway, Render, or Fly.io (all have free tiers).

---

## 1. Deploy the Backend

### Option A: Railway (Recommended — free tier, 1-click)

1. Push `main.py`, `requirements.txt`, `Dockerfile` to a GitHub repo
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Railway auto-detects the Dockerfile
4. Set environment variables in Railway dashboard:
   ```
   GROQ_API_KEY=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
   CARTESIA_API_KEY=sk_car_c77D8tBJjLttDgy9aSiasX
   ```
5. Copy your Railway URL: `https://your-app.up.railway.app`

### Option B: Render (also free)

1. Create account at https://render.com
2. New → Web Service → connect GitHub repo
3. Environment: Docker
4. Same env vars as above

### Option C: Local development

```bash
pip install -r requirements.txt
python main.py
# Runs at http://localhost:8000
```

---

## 2. Deploy the React Frontend

### Setup React project

```bash
npx create-react-app telecaller-frontend
cd telecaller-frontend
# Copy TelecallerTrainer.jsx into src/
```

Or with Vite:
```bash
npm create vite@latest telecaller-frontend -- --template react
cd telecaller-frontend
npm install
# Copy TelecallerTrainer.jsx into src/
```

Update `App.jsx`:
```jsx
import TelecallerTrainer from './TelecallerTrainer';
export default function App() { return <TelecallerTrainer />; }
```

### Configure API URL

In `TelecallerTrainer.jsx`, line 5:
```js
const API_BASE = "https://your-railway-url.up.railway.app"; // ← your backend URL
```

### Deploy to Vercel

```bash
npm run build
npx vercel --prod
```

---

## 3. API Reference

### Session flow:

```
POST /session/create          → { session_id, greeting_audio_b64, ... }
POST /session/:id/turn        → send audio file, get response audio
POST /session/:id/evaluate    → end session, get full evaluation
```

### All endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/profiles` | List all customer profiles |
| GET | `/difficulties` | List difficulty levels |
| POST | `/session/create` | Start a new session |
| GET | `/session/:id` | Get session status |
| POST | `/session/:id/turn` | Audio turn (multipart/form-data) |
| POST | `/session/:id/turn/text` | Text-only turn |
| POST | `/session/:id/evaluate` | End & evaluate session |
| DELETE | `/session/:id` | Delete session from memory |

### Example: Create session
```js
const res = await fetch('https://your-api.railway.app/session/create', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    profile_id: 'skeptical_businessman',
    difficulty: 'intermediate'
  })
});
const { session_id, greeting_audio_b64 } = await res.json();
```

### Example: Send audio turn
```js
const form = new FormData();
form.append('audio', audioBlob, 'recording.webm');
const res = await fetch(`https://your-api.railway.app/session/${sessionId}/turn`, {
  method: 'POST',
  body: form
});
const { transcription, response_text, response_audio_b64, session_ended } = await res.json();
```

---

## 4. Production checklist

- [ ] Set `allow_origins` in CORS to your specific frontend domain
- [ ] Add Redis for session storage (SESSIONS dict is in-memory only)
- [ ] Add rate limiting (per IP / per user)
- [ ] Rotate API keys and store as env vars, never in code
- [ ] Enable HTTPS (Railway/Render do this automatically)

---

## Files

```
telecaller-api/
├── main.py              ← FastAPI backend (deploy this)
├── requirements.txt     ← Python dependencies
├── Dockerfile           ← For Railway/Render/Fly.io
├── TelecallerTrainer.jsx ← React component (put in your React app)
└── DEPLOYMENT.md        ← This file
```
