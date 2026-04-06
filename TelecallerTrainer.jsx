import { useState, useRef, useEffect, useCallback } from "react";

// ── CONFIG ──────────────────────────────────────────────────────────
const API_BASE = "http://localhost:8000"; // ← change to your deployed API URL

// ══════════════════════════════════════════════════════════════════
// AUDIO UTILITIES
// ══════════════════════════════════════════════════════════════════

function base64ToAudioBuffer(b64, sampleRate = 22050) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

async function playAudioB64(b64) {
  if (!b64) return;
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const buf = base64ToAudioBuffer(b64);
  const decoded = await ctx.decodeAudioData(buf);
  const src = ctx.createBufferSource();
  src.buffer = decoded;
  src.connect(ctx.destination);
  return new Promise((res) => {
    src.onended = () => { ctx.close(); res(); };
    src.start();
  });
}

// ══════════════════════════════════════════════════════════════════
// HOOKS
// ══════════════════════════════════════════════════════════════════

function useAudioRecorder() {
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const analyserRef = useRef(null);
  const animRef = useRef(null);
  const streamRef = useRef(null);

  const startRecording = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;

    // Audio level analyser
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    const src = ctx.createMediaStreamSource(stream);
    src.connect(analyser);
    analyserRef.current = analyser;

    const data = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      analyser.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length;
      setAudioLevel(Math.min(100, avg * 2));
      animRef.current = requestAnimationFrame(tick);
    };
    tick();

    const mr = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
    chunksRef.current = [];
    mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
    mr.start();
    mediaRecorderRef.current = mr;
    setIsRecording(true);
  }, []);

  const stopRecording = useCallback(() => {
    return new Promise((resolve) => {
      const mr = mediaRecorderRef.current;
      if (!mr) { resolve(null); return; }
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        resolve(blob);
      };
      mr.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      cancelAnimationFrame(animRef.current);
      setAudioLevel(0);
      setIsRecording(false);
    });
  }, []);

  return { isRecording, audioLevel, startRecording, stopRecording };
}

// ══════════════════════════════════════════════════════════════════
// COMPONENTS
// ══════════════════════════════════════════════════════════════════

const PROFILES_STATIC = [
  { id: "skeptical_businessman", name: "Robert Chen", description: "Skeptical 46-year-old, guarded on cold calls", emoji: "🤨" },
  { id: "busy_working_mom",      name: "Sarah Johnson", description: "Distracted 34-year-old, already half-checked out", emoji: "😤" },
  { id: "price_hawk",            name: "Mike Thompson", description: "Blunt 40-year-old, everything is about the price", emoji: "💰" },
  { id: "confused_retiree",      name: "Dorothy Williams", description: "Elderly 69-year-old, mishears things", emoji: "👵" },
  { id: "demanding_guy",         name: "James Miller", description: "Blunt 52-year-old, zero patience", emoji: "😤" },
  { id: "millennial_professional", name: "Emily Davis", description: "29-year-old, clocks scripted pitches instantly", emoji: "🧐" },
];

const DIFFICULTIES = [
  { id: "beginner",     label: "Beginner",     emoji: "🟢", desc: "Cooperative customer, 1 soft objection" },
  { id: "intermediate", label: "Intermediate", emoji: "🟡", desc: "Moderate resistance, 2-3 objections" },
  { id: "advanced",     label: "Advanced",     emoji: "🔴", desc: "Very difficult, will push back hard" },
];

// ── Score Bar ──────────────────────────────────────────────────────

function ScoreBar({ score, max = 10 }) {
  const pct = (score / max) * 100;
  const color = score >= 7 ? "#4ade80" : score >= 5 ? "#facc15" : "#f87171";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{
        flex: 1, height: 6, background: "#1e293b", borderRadius: 3, overflow: "hidden"
      }}>
        <div style={{
          width: `${pct}%`, height: "100%", background: color,
          borderRadius: 3, transition: "width 1s ease"
        }} />
      </div>
      <span style={{ color, fontWeight: 700, fontSize: 13, minWidth: 32 }}>{score}/10</span>
    </div>
  );
}

// ── Waveform Bars ──────────────────────────────────────────────────

function WaveBars({ level, active }) {
  const bars = 20;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 3, height: 40 }}>
      {Array.from({ length: bars }).map((_, i) => {
        const phase = (i / bars) * Math.PI;
        const h = active
          ? Math.max(4, Math.sin(phase) * level * 0.4 + Math.random() * level * 0.2)
          : 4;
        return (
          <div key={i} style={{
            width: 3, height: h, minHeight: 4, maxHeight: 36,
            background: active ? "#38bdf8" : "#334155",
            borderRadius: 2, transition: "height 0.05s ease",
          }} />
        );
      })}
    </div>
  );
}

// ── Transcript Item ────────────────────────────────────────────────

function TranscriptItem({ item }) {
  const isTC = item.role === "telecaller";
  return (
    <div style={{
      display: "flex", justifyContent: isTC ? "flex-end" : "flex-start",
      marginBottom: 12,
    }}>
      <div style={{
        maxWidth: "75%",
        background: isTC ? "#0f4c81" : "#1e293b",
        border: `1px solid ${isTC ? "#3b82f6" : "#334155"}`,
        borderRadius: isTC ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
        padding: "10px 14px",
      }}>
        <div style={{
          fontSize: 10, color: isTC ? "#93c5fd" : "#64748b",
          fontWeight: 700, marginBottom: 4, textTransform: "uppercase", letterSpacing: 1
        }}>
          {isTC ? "You" : "Customer"}
        </div>
        <div style={{ fontSize: 14, color: "#e2e8f0", lineHeight: 1.5 }}>{item.text}</div>
      </div>
    </div>
  );
}

// ── Evaluation Report ──────────────────────────────────────────────

function EvalReport({ data }) {
  const ev = data.evaluation;
  if (!ev || ev.error) return <div style={{ color: "#f87171" }}>Evaluation failed.</div>;

  const criteriaLabels = {
    fluency: "Fluency", pronunciation: "Pronunciation",
    american_english_accent: "Accent", professionalism: "Professionalism",
    active_listening: "Active Listening", product_knowledge: "Product Knowledge",
    objection_handling: "Objection Handling", closing_ability: "Closing Ability",
    empathy: "Empathy", confidence: "Confidence",
  };

  const overall = ev.overall_score || 0;
  const grade = ev.grade || "?";
  const gradeColor = overall >= 7 ? "#4ade80" : overall >= 5 ? "#facc15" : "#f87171";

  return (
    <div style={{ animation: "fadeIn 0.5s ease" }}>
      {/* Header */}
      <div style={{
        background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
        border: "1px solid #334155", borderRadius: 16,
        padding: 24, marginBottom: 20, textAlign: "center"
      }}>
        <div style={{ fontSize: 48, marginBottom: 8 }}>📊</div>
        <div style={{ fontSize: 13, color: "#64748b", marginBottom: 4 }}>
          {data.customer} · {data.difficulty?.toUpperCase()} · {Math.round(data.duration_secs / 60)}m {data.duration_secs % 60 | 0}s · {data.total_turns} turns
        </div>
        <div style={{ fontSize: 64, fontWeight: 900, color: gradeColor, lineHeight: 1 }}>{grade}</div>
        <div style={{ fontSize: 18, color: "#94a3b8" }}>{overall.toFixed(1)} / 10</div>
      </div>

      {/* Scores */}
      <div style={{
        background: "#0f172a", border: "1px solid #1e293b", borderRadius: 16, padding: 20, marginBottom: 20
      }}>
        <div style={{ fontSize: 12, color: "#64748b", fontWeight: 700, letterSpacing: 1, marginBottom: 16 }}>DETAILED SCORES</div>
        {Object.entries(criteriaLabels).map(([key, label]) => {
          const entry = ev.scores?.[key] || {};
          return (
            <div key={key} style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontSize: 13, color: "#94a3b8", fontWeight: 600 }}>{label}</span>
              </div>
              <ScoreBar score={entry.score || 0} />
              <div style={{ fontSize: 12, color: "#475569", marginTop: 4 }}>{entry.feedback}</div>
            </div>
          );
        })}
      </div>

      {/* Strengths + Improvements */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
        <div style={{ background: "#052e16", border: "1px solid #166534", borderRadius: 12, padding: 16 }}>
          <div style={{ fontSize: 11, color: "#4ade80", fontWeight: 700, marginBottom: 12 }}>✦ STRENGTHS</div>
          {(ev.strongest_moments || []).filter(Boolean).map((m, i) => (
            <div key={i} style={{ fontSize: 12, color: "#86efac", marginBottom: 8, lineHeight: 1.5 }}>• {m}</div>
          ))}
        </div>
        <div style={{ background: "#2d1003", border: "1px solid #92400e", borderRadius: 12, padding: 16 }}>
          <div style={{ fontSize: 11, color: "#fb923c", fontWeight: 700, marginBottom: 12 }}>⚠ IMPROVE</div>
          {(ev.improvement_areas || []).filter(Boolean).map((item, i) => (
            <div key={i} style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 12, color: "#fdba74", fontWeight: 600 }}>{item.area}</div>
              <div style={{ fontSize: 11, color: "#c2410c", lineHeight: 1.4 }}>{item.suggestion}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Summary */}
      <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 12, padding: 16 }}>
        <div style={{ fontSize: 11, color: "#64748b", fontWeight: 700, marginBottom: 8 }}>SUMMARY</div>
        <div style={{ fontSize: 13, color: "#cbd5e1", lineHeight: 1.7 }}>{ev.summary}</div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
// MAIN APP
// ══════════════════════════════════════════════════════════════════

export default function TelecallerTrainer() {
  const [screen, setScreen] = useState("setup"); // setup | session | evaluation
  const [selectedProfile, setSelectedProfile] = useState(null);
  const [selectedDifficulty, setSelectedDifficulty] = useState("intermediate");
  const [sessionData, setSessionData] = useState(null);
  const [transcript, setTranscript] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState("");
  const [isSpeaking, setIsSpeaking] = useState(false); // AI is speaking
  const [evalData, setEvalData] = useState(null);
  const [error, setError] = useState(null);
  const transcriptRef = useRef(null);

  const { isRecording, audioLevel, startRecording, stopRecording } = useAudioRecorder();

  // Auto-scroll transcript
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
    }
  }, [transcript]);

  // ── Start session ──────────────────────────────────────────────

  const startSession = async () => {
    if (!selectedProfile) return;
    setLoading(true);
    setLoadingMsg("Connecting to customer...");
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/session/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_id: selectedProfile.id, difficulty: selectedDifficulty }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSessionData(data);
      setTranscript([{ role: "customer", text: data.greeting_text }]);
      setScreen("session");

      // Play greeting
      if (data.greeting_audio_b64) {
        setIsSpeaking(true);
        await playAudioB64(data.greeting_audio_b64);
        setIsSpeaking(false);
      }
    } catch (e) {
      setError(`Failed to start session: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // ── Record turn ────────────────────────────────────────────────

  const handleMicPress = async () => {
    if (isSpeaking || loading) return;
    if (!isRecording) {
      await startRecording();
    } else {
      const blob = await stopRecording();
      if (!blob) return;
      await sendAudioTurn(blob);
    }
  };

  const sendAudioTurn = async (audioBlob) => {
    setLoading(true);
    setLoadingMsg("Transcribing...");
    try {
      const form = new FormData();
      form.append("audio", audioBlob, "recording.webm");
      const res = await fetch(`${API_BASE}/session/${sessionData.session_id}/turn`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      if (data.transcription) {
        setTranscript((t) => [...t, { role: "telecaller", text: data.transcription }]);
      }
      if (data.response_text) {
        setTranscript((t) => [...t, { role: "customer", text: data.response_text }]);
      }

      if (data.response_audio_b64) {
        setLoadingMsg("Customer speaking...");
        setIsSpeaking(true);
        await playAudioB64(data.response_audio_b64);
        setIsSpeaking(false);
      }

      if (data.session_ended) {
        await endSession();
      }
    } catch (e) {
      setError(`Turn failed: ${e.message}`);
    } finally {
      setLoading(false);
      setLoadingMsg("");
    }
  };

  // ── End & evaluate ─────────────────────────────────────────────

  const endSession = async () => {
    setLoading(true);
    setLoadingMsg("Generating your evaluation...");
    try {
      const res = await fetch(`${API_BASE}/session/${sessionData.session_id}/evaluate`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setEvalData(data);
      setScreen("evaluation");
    } catch (e) {
      setError(`Evaluation failed: ${e.message}`);
    } finally {
      setLoading(false);
      setLoadingMsg("");
    }
  };

  // ── Reset ──────────────────────────────────────────────────────

  const reset = () => {
    setScreen("setup");
    setSessionData(null);
    setTranscript([]);
    setEvalData(null);
    setError(null);
    setSelectedProfile(null);
  };

  // ══════════════════════════════════════════════════════════════
  // RENDER
  // ══════════════════════════════════════════════════════════════

  return (
    <div style={{
      minHeight: "100vh",
      background: "#020617",
      fontFamily: "'DM Mono', 'Fira Code', 'Courier New', monospace",
      color: "#e2e8f0",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@700;800;900&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #020617; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes ripple {
          0% { transform: scale(1); opacity: 0.6; }
          100% { transform: scale(2.5); opacity: 0; }
        }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 2px; }
      `}</style>

      {/* ── HEADER ─────────────────────────────────────────────── */}
      <div style={{
        borderBottom: "1px solid #1e293b",
        padding: "16px 24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        background: "#020617",
        position: "sticky", top: 0, zIndex: 100,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 32, height: 32, background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
            borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 16
          }}>📞</div>
          <div>
            <div style={{ fontFamily: "'Syne', sans-serif", fontWeight: 900, fontSize: 16, letterSpacing: -0.5 }}>
              TELECALLER TRAINER
            </div>
            <div style={{ fontSize: 10, color: "#475569", letterSpacing: 1 }}>AI-POWERED INSURANCE SALES SIMULATION</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {screen === "session" && (
            <div style={{
              display: "flex", alignItems: "center", gap: 6, fontSize: 11,
              color: "#4ade80", background: "#052e16", padding: "4px 10px", borderRadius: 20
            }}>
              <div style={{ width: 6, height: 6, background: "#4ade80", borderRadius: "50%", animation: "pulse 1.5s infinite" }} />
              LIVE
            </div>
          )}
          {screen !== "setup" && (
            <button onClick={reset} style={{
              background: "transparent", border: "1px solid #334155", color: "#94a3b8",
              fontSize: 11, padding: "6px 12px", borderRadius: 8, cursor: "pointer",
              letterSpacing: 1
            }}>NEW SESSION</button>
          )}
        </div>
      </div>

      {/* ── ERROR BANNER ───────────────────────────────────────── */}
      {error && (
        <div style={{
          background: "#450a0a", border: "1px solid #7f1d1d", color: "#fca5a5",
          padding: "10px 24px", fontSize: 13
        }}>
          ⚠ {error}
          <button onClick={() => setError(null)} style={{
            marginLeft: 12, background: "transparent", border: "none", color: "#fca5a5", cursor: "pointer"
          }}>✕</button>
        </div>
      )}

      {/* ── LOADING OVERLAY ────────────────────────────────────── */}
      {loading && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(2,6,23,0.8)",
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          zIndex: 200, backdropFilter: "blur(4px)"
        }}>
          <div style={{
            width: 40, height: 40, border: "3px solid #1e293b",
            borderTop: "3px solid #3b82f6", borderRadius: "50%",
            animation: "spin 0.8s linear infinite", marginBottom: 16
          }} />
          <div style={{ fontSize: 13, color: "#94a3b8" }}>{loadingMsg}</div>
        </div>
      )}

      <div style={{ maxWidth: 720, margin: "0 auto", padding: "32px 20px" }}>

        {/* ════════════════════════════════════════════════════════
            SETUP SCREEN
        ════════════════════════════════════════════════════════ */}
        {screen === "setup" && (
          <div style={{ animation: "fadeIn 0.4s ease" }}>
            <div style={{ textAlign: "center", marginBottom: 48 }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>📞</div>
              <h1 style={{
                fontFamily: "'Syne', sans-serif", fontWeight: 900,
                fontSize: 36, letterSpacing: -1.5, marginBottom: 8
              }}>
                Ready to Train?
              </h1>
              <p style={{ color: "#475569", fontSize: 14 }}>
                Practice insurance sales calls against AI customers. <br />Get scored on 10 criteria.
              </p>
            </div>

            {/* Difficulty */}
            <div style={{ marginBottom: 32 }}>
              <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, fontWeight: 700, marginBottom: 12 }}>
                01 — SELECT DIFFICULTY
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
                {DIFFICULTIES.map((d) => (
                  <button key={d.id} onClick={() => setSelectedDifficulty(d.id)} style={{
                    background: selectedDifficulty === d.id ? "#0f172a" : "transparent",
                    border: `1px solid ${selectedDifficulty === d.id ? "#3b82f6" : "#1e293b"}`,
                    borderRadius: 12, padding: "14px 12px", cursor: "pointer",
                    textAlign: "left", color: "#e2e8f0", transition: "all 0.15s",
                  }}>
                    <div style={{ fontSize: 18, marginBottom: 4 }}>{d.emoji}</div>
                    <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 2 }}>{d.label}</div>
                    <div style={{ fontSize: 10, color: "#475569", lineHeight: 1.4 }}>{d.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Profiles */}
            <div style={{ marginBottom: 40 }}>
              <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, fontWeight: 700, marginBottom: 12 }}>
                02 — CHOOSE CUSTOMER
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {PROFILES_STATIC.map((p) => (
                  <button key={p.id} onClick={() => setSelectedProfile(p)} style={{
                    background: selectedProfile?.id === p.id ? "#0f172a" : "transparent",
                    border: `1px solid ${selectedProfile?.id === p.id ? "#3b82f6" : "#1e293b"}`,
                    borderRadius: 12, padding: "14px 16px", cursor: "pointer",
                    textAlign: "left", color: "#e2e8f0", transition: "all 0.15s",
                    display: "flex", gap: 12, alignItems: "flex-start"
                  }}>
                    <div style={{ fontSize: 24 }}>{p.emoji}</div>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 2 }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: "#475569", lineHeight: 1.4 }}>{p.description}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <button
              onClick={startSession}
              disabled={!selectedProfile || loading}
              style={{
                width: "100%", padding: "18px",
                background: selectedProfile
                  ? "linear-gradient(135deg, #2563eb, #7c3aed)"
                  : "#1e293b",
                border: "none", borderRadius: 14, cursor: selectedProfile ? "pointer" : "not-allowed",
                color: selectedProfile ? "#fff" : "#475569",
                fontFamily: "'Syne', sans-serif", fontWeight: 900,
                fontSize: 16, letterSpacing: 0.5, transition: "all 0.2s",
              }}
            >
              {selectedProfile ? `📞 Call ${selectedProfile.name}` : "Select a customer to continue"}
            </button>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════
            SESSION SCREEN
        ════════════════════════════════════════════════════════ */}
        {screen === "session" && sessionData && (
          <div style={{ animation: "fadeIn 0.4s ease" }}>
            {/* Session info bar */}
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              background: "#0f172a", border: "1px solid #1e293b",
              borderRadius: 12, padding: "12px 16px", marginBottom: 20
            }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700 }}>{sessionData.profile?.name}</div>
                <div style={{ fontSize: 11, color: "#475569" }}>{sessionData.profile?.description}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 11, color: "#64748b" }}>DIFFICULTY</div>
                <div style={{ fontSize: 13, color: "#94a3b8" }}>
                  {DIFFICULTIES.find(d => d.id === selectedDifficulty)?.emoji}{" "}
                  {DIFFICULTIES.find(d => d.id === selectedDifficulty)?.label}
                </div>
              </div>
            </div>

            {/* Transcript */}
            <div ref={transcriptRef} style={{
              height: 360, overflowY: "auto", marginBottom: 24,
              background: "#0a0f1e", border: "1px solid #1e293b",
              borderRadius: 16, padding: 20,
            }}>
              {transcript.map((item, i) => <TranscriptItem key={i} item={item} />)}
              {isSpeaking && (
                <div style={{ display: "flex", gap: 4, padding: "4px 0 0 4px" }}>
                  {[0, 1, 2].map(i => (
                    <div key={i} style={{
                      width: 8, height: 8, background: "#8b5cf6", borderRadius: "50%",
                      animation: `pulse 1s infinite ${i * 0.2}s`
                    }} />
                  ))}
                </div>
              )}
            </div>

            {/* Mic controls */}
            <div style={{
              background: "#0f172a", border: "1px solid #1e293b",
              borderRadius: 20, padding: 24, textAlign: "center"
            }}>
              {/* Waveform */}
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 20 }}>
                <WaveBars level={audioLevel} active={isRecording} />
              </div>

              <div style={{ marginBottom: 8, fontSize: 12, color: "#475569" }}>
                {isSpeaking ? "Customer speaking..." :
                 isRecording ? "🎙 Recording — tap to send" :
                 loading ? loadingMsg :
                 "Tap mic to speak"}
              </div>

              {/* Big mic button */}
              <div style={{ position: "relative", display: "inline-block" }}>
                {isRecording && (
                  <div style={{
                    position: "absolute", inset: -8, borderRadius: "50%",
                    border: "2px solid #ef4444", animation: "ripple 1.5s infinite",
                  }} />
                )}
                <button
                  onMouseDown={handleMicPress}
                  disabled={isSpeaking || loading}
                  style={{
                    width: 80, height: 80, borderRadius: "50%",
                    background: isRecording
                      ? "linear-gradient(135deg, #dc2626, #9f1239)"
                      : isSpeaking || loading
                        ? "#1e293b"
                        : "linear-gradient(135deg, #2563eb, #7c3aed)",
                    border: "none", cursor: isSpeaking || loading ? "not-allowed" : "pointer",
                    fontSize: 28, transition: "all 0.15s",
                    boxShadow: isRecording ? "0 0 24px rgba(220,38,38,0.4)" : "none",
                  }}
                >
                  {isRecording ? "⏹" : "🎙"}
                </button>
              </div>

              {/* End call */}
              <div style={{ marginTop: 24 }}>
                <button onClick={endSession} style={{
                  background: "transparent", border: "1px solid #334155",
                  color: "#64748b", fontSize: 12, padding: "8px 20px",
                  borderRadius: 20, cursor: "pointer", letterSpacing: 1
                }}>
                  📴 END CALL & EVALUATE
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ════════════════════════════════════════════════════════
            EVALUATION SCREEN
        ════════════════════════════════════════════════════════ */}
        {screen === "evaluation" && evalData && (
          <div style={{ animation: "fadeIn 0.4s ease" }}>
            <EvalReport data={evalData} />

            {/* Transcript toggle */}
            <details style={{ marginTop: 20 }}>
              <summary style={{
                cursor: "pointer", fontSize: 12, color: "#64748b",
                letterSpacing: 1, userSelect: "none", padding: "12px 0"
              }}>
                VIEW FULL TRANSCRIPT ▸
              </summary>
              <div style={{
                background: "#0a0f1e", border: "1px solid #1e293b",
                borderRadius: 16, padding: 20, marginTop: 8
              }}>
                {evalData.transcript?.map((item, i) => <TranscriptItem key={i} item={item} />)}
              </div>
            </details>

            <button onClick={reset} style={{
              width: "100%", marginTop: 24, padding: "16px",
              background: "linear-gradient(135deg, #2563eb, #7c3aed)",
              border: "none", borderRadius: 14, cursor: "pointer",
              fontFamily: "'Syne', sans-serif", fontWeight: 900,
              fontSize: 16, color: "#fff", letterSpacing: 0.5
            }}>
              📞 PRACTICE AGAIN
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
