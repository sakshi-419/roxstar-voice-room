import os
from PIL import Image, ImageDraw, ImageFont

os.makedirs(r"c:\AI-VOICE-ROOM-ROCK\roxstar-voice-room\docs", exist_ok=True)

def get_font(size, bold=False):
    font_paths = [
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf"
    ]
    if bold:
        font_paths = [
            "C:\\Windows\\Fonts\\segoeuib.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\calibrib.ttf"
        ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

font_title = get_font(28, bold=True)
font_h2 = get_font(18, bold=True)
font_body = get_font(14, bold=False)
font_body_bold = get_font(14, bold=True)
font_small = get_font(11, bold=False)

def draw_rounded_rect(draw, box, fill, outline=None, width=1, radius=10):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

# 1. GENERATE ARCHITECTURE DIAGRAM
w, h = 1300, 960
img = Image.new("RGB", (w, h), "#0a0e17")
draw = ImageDraw.Draw(img)

draw_rounded_rect(draw, [30, 25, w - 30, 95], fill="#111827", outline="#1f2937", radius=12)
draw.text((50, 40), "Roxstar AI Voice Room — Production Architecture", fill="#38bdf8", font=font_title)
draw.text((50, 72), "Multi-Host Dual Persona (Dost & Sathi) · Ultra-Low Latency Voice Mesh", fill="#94a3b8", font=font_small)

def draw_card(x, y, cw, ch, title, sub, bg="#131d2e", border="#2563eb", title_color="#60a5fa"):
    draw_rounded_rect(draw, [x, y, x + cw, y + ch], fill=bg, outline=border, width=2, radius=10)
    draw.text((x + 15, y + 12), title, fill=title_color, font=font_h2)
    lines = sub.split("\n")
    cur_y = y + 38
    for line in lines:
        draw.text((x + 15, cur_y), line, fill="#cbd5e1", font=font_small)
        cur_y += 18

draw_card(50, 120, 360, 110, "1. Human Participants", "• Bidirectional Audio & Live Text Chat\n• React + Vite + TypeScript SPA\n• Deployed on Vercel Edge Global CDN", border="#38bdf8", title_color="#38bdf8")
draw_card(460, 120, 380, 110, "2. Token Server (Web Service)", "• FastAPI JWT generation & dispatch\n• Idempotent agent summon with Redis locks\n• Deployed on Render Web Service ($PORT)", border="#10b981", title_color="#34d399")
draw_card(890, 120, 360, 110, "3. Upstash Redis (State/Locks)", "• Speaking Lock (Mutex Barge-in)\n• Active Persona Lock (Anti-duplicate)\n• 10-turn Conversation Memory", border="#f59e0b", title_color="#fbbf24")

draw.line([(230, 230), (230, 270)], fill="#38bdf8", width=3)
draw.polygon([(225, 268), (235, 268), (230, 278)], fill="#38bdf8")
draw.line([(650, 230), (650, 270)], fill="#34d399", width=3)
draw.polygon([(645, 268), (655, 268), (650, 278)], fill="#34d399")
draw.line([(1070, 230), (1070, 480)], fill="#fbbf24", width=3)
draw.polygon([(1065, 478), (1075, 478), (1070, 488)], fill="#fbbf24")

draw_card(50, 280, 790, 100, "LiveKit Cloud — Global Realtime Voice Room", "• WebRTC Low-Latency Mesh Audio Streaming\n• Participant Presence, Active Speaker Detection & Data Packets\n• Agent Dispatch Gateway & Room State Sync", bg="#162238", border="#0284c7", title_color="#38bdf8")

draw.line([(445, 380), (445, 420)], fill="#38bdf8", width=3)
draw.polygon([(440, 418), (450, 418), (445, 428)], fill="#38bdf8")

draw_rounded_rect(draw, [50, 430, 1250, 890], fill="#0f172a", outline="#334155", width=2, radius=12)
draw.text((70, 445), "LiveKit Agent Worker (Persistent Process / Render Background Worker)", fill="#f8fafc", font=font_h2)
draw.text((70, 472), "Command: uv run python -m server.main start  ·  Continuous Room Subscription & Voice Turn Orchestration", fill="#94a3b8", font=font_small)

draw_card(80, 505, 330, 95, "Stage 1: Deepgram Nova-3 STT", "• Multilingual Hindi / Hinglish / English\n• Realtime streaming audio transcription\n• Self-audio loopback echo filter", border="#a855f7", title_color="#c084fc")

draw.line([(410, 552), (470, 552)], fill="#c084fc", width=3)
draw.polygon([(468, 547), (468, 557), (478, 552)], fill="#c084fc")

draw_card(480, 505, 370, 140, "Stage 2: Layered BotRouter", "1. Explicit Address ('Dost...', 'Sathi...')\n2. Context Continuation ('Thoda simple...')\n3. Affinity & Semantic Relevance\n4. Alternation & Distributed Fallback\n→ Exactly ONE bot selected per human turn", border="#ec4899", title_color="#f472b6")

draw.line([(850, 550), (910, 530)], fill="#f472b6", width=2)
draw.polygon([(908, 525), (908, 535), (918, 530)], fill="#f472b6")
draw.line([(850, 590), (910, 620)], fill="#f472b6", width=2)
draw.polygon([(908, 615), (908, 625), (918, 620)], fill="#f472b6")

draw_card(920, 490, 310, 75, "Roxstar AI Dost (Male Co-Host)", "• Energetic, friendly Hindi brotherly vibe\n• Hindi/Hinglish idiom mastery", border="#38bdf8", title_color="#38bdf8")
draw_card(920, 580, 310, 75, "Roxstar AI Sathi (Female Co-Host)", "• Empathetic, articulate, patient Hindi guide\n• Collaborative multi-host synergy", border="#ec4899", title_color="#f472b6")

draw.line([(1075, 565), (1075, 575)], fill="#64748b", width=2)
draw.line([(1075, 655), (1075, 680)], fill="#f472b6", width=2)
draw.polygon([(1070, 678), (1080, 678), (1075, 688)], fill="#f472b6")

draw_card(800, 690, 430, 95, "Stage 3: Groq LLM Inference", "• Primary: groq/compound-mini (<300ms TTFT)\n• Fallback: allam-2-7b\n• Hindi/Hinglish context injection & bounds", border="#f97316", title_color="#fb923c")

draw.line([(800, 737), (740, 737)], fill="#fb923c", width=3)
draw.polygon([(742, 732), (742, 742), (732, 737)], fill="#fb923c")

draw_card(370, 690, 360, 95, "Stage 4: ElevenLabs Flash v2.5 TTS", "• Ultra-fast low latency streaming audio\n• Dost: Male Hindi Voice ID\n• Sathi: Female Hindi Voice ID", border="#10b981", title_color="#34d399")

draw.line([(370, 737), (210, 737), (210, 380)], fill="#34d399", width=3)
draw.polygon([(205, 382), (215, 382), (210, 372)], fill="#34d399")

draw.text((70, 925), "Security: Zero hardcoded secrets · API keys in environment · Safe for production deployment", fill="#64748b", font=font_small)

img.save(r"c:\AI-VOICE-ROOM-ROCK\roxstar-voice-room\docs\architecture.png")
print("architecture.png created successfully")

# 2. GENERATE SEQUENCE DIAGRAM
sw, sh = 1400, 1020
simg = Image.new("RGB", (sw, sh), "#0a0e17")
sdraw = ImageDraw.Draw(simg)

draw_rounded_rect(sdraw, [30, 20, sw - 30, 85], fill="#111827", outline="#1f2937", radius=10)
sdraw.text((50, 35), "Roxstar AI Voice Room — Sequence Diagram", fill="#38bdf8", font=font_title)
sdraw.text((50, 65), "End-to-End Speech Turn Handling · Follow-Up Context Continuity · Single-Speaker Arbitration", fill="#94a3b8", font=font_small)

cols = [
    ("Human", 120),
    ("React (Vercel)", 300),
    ("LiveKit Cloud", 490),
    ("STT (Deepgram)", 680),
    ("BotRouter", 870),
    ("Groq LLM", 1060),
    ("ElevenLabs TTS", 1250),
]

for name, cx in cols:
    draw_rounded_rect(sdraw, [cx - 65, 105, cx + 65, 145], fill="#1e293b", outline="#38bdf8", radius=8)
    sdraw.text((cx - 50, 118), name, fill="#f8fafc", font=font_body_bold)
    y = 150
    while y < sh - 40:
        sdraw.line([(cx, y), (cx, y + 8)], fill="#334155", width=2)
        y += 16

def draw_seq_arrow(x1, x2, y, label, color="#38bdf8"):
    sdraw.line([(x1, y), (x2, y)], fill=color, width=2)
    if x2 > x1:
        sdraw.polygon([(x2 - 8, y - 5), (x2 - 8, y + 5), (x2, y)], fill=color)
    else:
        sdraw.polygon([(x2 + 8, y - 5), (x2 + 8, y + 5), (x2, y)], fill=color)
    mid_x = (x1 + x2) // 2
    sdraw.text((mid_x - 90, y - 18), label, fill=color, font=font_small)

def draw_block_note(y, text, fill="#1e293b", border="#3b82f6"):
    draw_rounded_rect(sdraw, [50, y, sw - 50, y + 28], fill=fill, outline=border, radius=6)
    sdraw.text((65, y + 6), text, fill="#e2e8f0", font=font_body_bold)

draw_block_note(170, 'SCENARIO 1: Direct Addressing — "Hi Dost, AI kya hota hai?"', fill="#1e1b4b", border="#6366f1")

draw_seq_arrow(120, 300, 220, '1. Speaks: "Dost, AI kya hota hai?"', "#38bdf8")
draw_seq_arrow(300, 490, 250, '2. WebRTC Audio Stream', "#38bdf8")
draw_seq_arrow(490, 680, 280, '3. Raw Audio Frames', "#a855f7")
draw_seq_arrow(680, 870, 310, '4. Transcript: "Dost, AI kya hota hai?"', "#c084fc")

draw_rounded_rect(sdraw, [810, 325, 930, 355], fill="#312e81", outline="#818cf8", radius=4)
sdraw.text((818, 332), "Router: Dost selected", fill="#e0e7ff", font=font_small)

draw_seq_arrow(870, 1060, 375, "5. Generate prompt + history", "#fb923c")
draw_seq_arrow(1060, 1250, 410, "6. Stream tokens to TTS", "#10b981")
draw_seq_arrow(1250, 490, 450, "7. Audio Stream (Dost voice)", "#34d399")
draw_seq_arrow(490, 120, 485, "8. Dost speaks Hindi in user headphones", "#38bdf8")

draw_block_note(525, 'SCENARIO 2: Context Continuation — "Thoda simple batao" (No bot name mentioned)', fill="#064e3b", border="#10b981")

draw_seq_arrow(120, 300, 575, '9. Speaks: "Thoda simple batao"', "#38bdf8")
draw_seq_arrow(300, 490, 605, "10. WebRTC Audio Stream", "#38bdf8")
draw_seq_arrow(490, 680, 635, "11. Raw Audio Frames", "#a855f7")
draw_seq_arrow(680, 870, 665, '12. Transcript: "Thoda simple batao"', "#c084fc")

draw_rounded_rect(sdraw, [760, 680, 980, 715], fill="#065f46", outline="#34d399", radius=4)
sdraw.text((770, 688), "Context: Follow-up goes to Dost", fill="#d1fae5", font=font_small)

draw_seq_arrow(870, 1060, 735, "13. Persona Dost continues context", "#fb923c")
draw_seq_arrow(1060, 1250, 770, "14. Stream tokens to TTS", "#10b981")
draw_seq_arrow(1250, 490, 810, "15. Audio Stream (Dost voice)", "#34d399")
draw_seq_arrow(490, 120, 845, "16. User hears Dost's simplified answer", "#38bdf8")

draw_block_note(880, "SAFETY RULES: Single-Speaker Mutex, Barge-in Interruption, and Self-Audio Filter", fill="#451a03", border="#d97706")

draw_rounded_rect(sdraw, [100, 925, sw - 100, 985], fill="#1c1917", outline="#78716c", radius=6)
sdraw.text((120, 935), "• Sathi remains completely silent during Dost's turn (Redis speaking lock enforces strict 1-agent arbitration).", fill="#fde68a", font=font_small)
sdraw.text((120, 955), "• If Human interrupts while AI is speaking: LiveKit VAD cancels pending TTS playback immediately (Barge-in).", fill="#fde68a", font=font_small)
sdraw.text((120, 970), "• AI self-audio loopback prevention: RoomAudioRenderer output is isolated from the STT input stream.", fill="#fde68a", font=font_small)

simg.save(r"c:\AI-VOICE-ROOM-ROCK\roxstar-voice-room\docs\sequence-diagram.png")
print("sequence-diagram.png created successfully")
