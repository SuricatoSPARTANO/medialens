import os
import json
import tempfile
import subprocess
import time

try:
    subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
except Exception:
    subprocess.run(["apt-get", "install", "-y", "ffmpeg"], capture_output=True)

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ─── PROMPTS ────────────────────────────────────────────────────────────────

PHASE0_PROMPT = """Sei un esperto di comunicazione e media. Analizza il seguente contenuto e classifica il tipo.

CONTENUTO:
\"\"\"{text}\"\"\"

Restituisci SOLO JSON valido (nessun markdown, nessun backtick):
{{
  "content_type": "<uno tra: informativo|politico|attivista|testimoniale|educativo|intrattenimento|commerciale|misto|complottista|satirico>",
  "content_type_label": "<nome leggibile in italiano>",
  "intent": "<descrizione breve dell'intento principale, 1 frase>",
  "target_audience": "<pubblico a cui si rivolge, 1 frase>",
  "guiding_question": "<la domanda critica principale da farsi su questo contenuto, 1 frase>",
  "risk_profile": "<low|medium|high>",
  "classification_note": "<spiegazione della classificazione, 2-3 frasi>"
}}"""

PHASE1_PROMPTS = {
  "informativo": """Analizza questo contenuto informativo. Concentrati su: accuratezza, completezza, fonti citate, contesto fornito, cosa manca.
CONTENUTO: \"\"\"{text}\"\"\"
Restituisci SOLO JSON valido:
{{
  "risk_score_claims": <0-100>,
  "risk_score_framing": <0-100>,
  "risk_score_bias": <0-100>,
  "risk_score_rhetoric": <0-100>,
  "claims_level": "<Nessun claim|Basso|Moderato|Alto|Grave>",
  "claims_summary": "<analisi dei claim>",
  "claims": [{{"claim":"<testo>","verdict_label":"<Verificato|Parzialmente vero|Falso|Non verificabile>","verdict_key":"<true|partial|false|unverifiable>","color":"<green|yellow|red>","explanation":"<spiegazione>"}}],
  "framing_level": "<Assente|Basso|Moderato|Alto|Molto alto>",
  "framing_analysis": "<analisi>",
  "framing_examples": "<esempi>",
  "bias_level": "<Assente|Lieve|Moderato|Forte|Molto forte>",
  "bias_analysis": "<analisi>",
  "bias_spectrum": "<posizionamento>",
  "rhetoric_level": "<Assente|Basso|Moderato|Alto|Molto alto>",
  "rhetoric_analysis": "<analisi>",
  "rhetoric_techniques": ["<tecnica>"],
  "omissions_level": "<Nessuna|Poche|Alcune|Molte|Sistematiche>",
  "omissions_analysis": "<analisi>",
  "omissions": ["<omissione>"],
  "overall_verdict": "<verdetto 3-4 frasi>",
  "reader_advice": "<consiglio 1-2 frasi>"
}}""",

  "testimoniale": """Analizza questo contenuto testimoniale/personale. Attenzione: l'emozione è il mezzo espressivo legittimo qui. Concentrati su: dove finisce la testimonianza e inizia la generalizzazione, se ci sono claim universali non supportati, se l'intento cambia nel corso del contenuto.
CONTENUTO: \"\"\"{text}\"\"\"
Restituisci SOLO JSON valido:
{{
  "risk_score_claims": <0-100, pesa poco l'emozione>,
  "risk_score_framing": <0-100, considera che l'emozione è legittima>,
  "risk_score_bias": <0-100>,
  "risk_score_rhetoric": <0-100, considera che la retorica personale è normale>,
  "claims_level": "<Nessun claim|Basso|Moderato|Alto|Grave>",
  "claims_summary": "<analisi focalizzata sulle generalizzazioni indebite>",
  "claims": [{{"claim":"<testo>","verdict_label":"<Verificato|Parzialmente vero|Falso|Non verificabile>","verdict_key":"<true|partial|false|unverifiable>","color":"<green|yellow|red>","explanation":"<spiegazione>"}}],
  "framing_level": "<Assente|Basso|Moderato|Alto|Molto alto>",
  "framing_analysis": "<distingui emozione legittima da framing manipolativo>",
  "framing_examples": "<esempi solo di framing problematico, non dell'emozione normale>",
  "bias_level": "<Assente|Lieve|Moderato|Forte|Molto forte>",
  "bias_analysis": "<analisi>",
  "bias_spectrum": "<posizionamento>",
  "rhetoric_level": "<Assente|Basso|Moderato|Alto|Molto alto>",
  "rhetoric_analysis": "<distingui retorica personale da tecniche manipolative>",
  "rhetoric_techniques": ["<solo tecniche realmente problematiche>"],
  "omissions_level": "<Nessuna|Poche|Alcune|Molte|Sistematiche>",
  "omissions_analysis": "<analisi>",
  "omissions": ["<omissione>"],
  "overall_verdict": "<verdetto calibrato sul formato testimoniale>",
  "reader_advice": "<consiglio 1-2 frasi>"
}}"""
}

PHASE1_DEFAULT = """Analizza questo contenuto di tipo {content_type}. Obiettivo critico: {guiding_question}
CONTENUTO: \"\"\"{text}\"\"\"
Restituisci SOLO JSON valido:
{{
  "risk_score_claims": <0-100>,
  "risk_score_framing": <0-100>,
  "risk_score_bias": <0-100>,
  "risk_score_rhetoric": <0-100>,
  "claims_level": "<Nessun claim|Basso|Moderato|Alto|Grave>",
  "claims_summary": "<analisi>",
  "claims": [{{"claim":"<testo>","verdict_label":"<Verificato|Parzialmente vero|Falso|Non verificabile>","verdict_key":"<true|partial|false|unverifiable>","color":"<green|yellow|red>","explanation":"<spiegazione>"}}],
  "framing_level": "<Assente|Basso|Moderato|Alto|Molto alto>",
  "framing_analysis": "<analisi>",
  "framing_examples": "<esempi>",
  "bias_level": "<Assente|Lieve|Moderato|Forte|Molto forte>",
  "bias_analysis": "<analisi>",
  "bias_spectrum": "<posizionamento>",
  "rhetoric_level": "<Assente|Basso|Moderato|Alto|Molto alto>",
  "rhetoric_analysis": "<analisi>",
  "rhetoric_techniques": ["<tecnica>"],
  "omissions_level": "<Nessuna|Poche|Alcune|Molte|Sistematiche>",
  "omissions_analysis": "<analisi>",
  "omissions": ["<omissione>"],
  "overall_verdict": "<verdetto 3-4 frasi>",
  "reader_advice": "<consiglio 1-2 frasi>"
}}"""

PHASE2_PROMPT = """Sei un fact-checker esperto. Hai accesso alla ricerca web. Verifica ogni claim della lista usando fonti primarie.

CLAIMS DA VERIFICARE:
{claims_json}

CONTESTO (tipo di contenuto): {content_type}

Per ogni claim cerca fonti primarie (leggi, studi scientifici, dati ufficiali, articoli giornalistici verificati).
Restituisci SOLO JSON valido:
{{
  "verified_claims": [
    {{
      "claim": "<testo del claim>",
      "verdict": "<Vero|Parzialmente vero|Falso|Non verificabile|Opinione>",
      "verdict_key": "<true|partial|false|unverifiable|opinion>",
      "confidence": "<Alta|Media|Bassa>",
      "explanation": "<spiegazione con dettagli concreti, 2-3 frasi>",
      "sources": ["<fonte 1>", "<fonte 2>"],
      "color": "<green|yellow|red>"
    }}
  ],
  "fact_check_summary": "<sintesi generale della verifica, 2-3 frasi>",
  "most_problematic": "<il claim più problematico identificato, 1 frase>",
  "most_solid": "<il claim più solido o verificato, 1 frase>"
}}"""

LIVE_CHUNK_PROMPT = """Analizza questo frammento di testo parlato e restituisci SOLO JSON valido.
FRAMMENTO (chunk #{chunk_num}): \"\"\"{text}\"\"\"
{{
  "risk_level": "<low|medium|high>",
  "risk_score": <0-100>,
  "flags": [{{"type":"<claim|framing|rhetoric|bias>","text":"<frase>","note":"<spiegazione>"}}],
  "techniques": ["<tecnica>"],
  "summary": "<una frase>"
}}"""



def sanitize_text(text):
    """Remove characters that break JSON encoding."""
    import re
    # Remove control characters except newlines and tabs
    text = re.sub(r'[--]', '', text)
    # Replace smart quotes and special dashes
    text = text.replace('“', '"').replace('”', '"')
    text = text.replace('‘', "'").replace('’', "'")
    text = text.replace('–', '-').replace('—', '-')
    # Truncate safely
    return text[:8000]

def call_claude(prompt, api_key, tools=None):
    body = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": prompt}]
    }
    if tools:
        body["tools"] = tools

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        },
        json=body,
        timeout=120
    )
    resp.raise_for_status()
    data = resp.json()
    raw = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


def call_claude_with_search(prompt, api_key):
    """Call Claude with web search enabled for fact-checking."""
    body = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 3000,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": prompt}]
    }
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "web-search-2025-03-05"
        },
        json=body,
        timeout=120
    )
    resp.raise_for_status()
    data = resp.json()
    raw = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


def transcribe_with_whisper(audio_path, api_key):
    with open(audio_path, "rb") as f:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (os.path.basename(audio_path), f, "audio/mp3")},
            data={"model": "whisper-1", "language": "it", "response_format": "text"},
            timeout=120
        )
        resp.raise_for_status()
        return resp.text


def download_audio(url):
    import shutil
    tmpdir = tempfile.mkdtemp()
    out_path = os.path.join(tmpdir, "audio")

    # Update yt-dlp first to get latest fixes
    subprocess.run(["pip", "install", "--upgrade", "yt-dlp", "--break-system-packages"],
                   capture_output=True, timeout=60)

    # Find JS runtime
    js_args = []
    for runtime in ["node", "nodejs", "deno", "phantomjs"]:
        path = shutil.which(runtime)
        if path:
            js_args = ["--js-runtimes", f"{runtime}:{path}"]
            break

    # Try with format selection that avoids JS requirement
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--max-filesize", "50m",
        "--ffmpeg-location", "/usr/bin",
        "-f", "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
        "--no-check-certificate",
    ] + js_args + [
        "-o", out_path + ".%(ext)s",
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    # Look for any downloaded file
    for ext in ["m4a", "mp3", "webm", "opus", "ogg", "wav", "mp4"]:
        candidate = out_path + "." + ext
        if os.path.exists(candidate):
            return candidate

    # Check tmpdir for any file
    files = [f for f in os.listdir(tmpdir) if not f.endswith('.part')]
    if files:
        return os.path.join(tmpdir, files[0])

    raise Exception(f"Download fallito: {result.stderr[:400]}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.json
    anthropic_key = data.get("anthropic_key") or ANTHROPIC_API_KEY
    openai_key = data.get("openai_key") or OPENAI_API_KEY
    mode = data.get("mode", "text")
    text = data.get("text", "")
    url = data.get("url", "")

    if not anthropic_key:
        return jsonify({"error": "Chiave API Anthropic mancante"}), 400

    try:
        # Download + transcribe if URL
        if mode == "url" and url:
            if not openai_key:
                return jsonify({"error": "Chiave API OpenAI necessaria per video/audio"}), 400
            audio_path = download_audio(url)
            text = transcribe_with_whisper(audio_path, openai_key)
            try:
                os.remove(audio_path)
            except:
                pass

        if not text or len(text.strip()) < 20:
            return jsonify({"error": "Testo troppo breve o vuoto"}), 400

        text_truncated = sanitize_text(text)

        # ── FASE 0: Classificazione ──────────────────────────────────────────
        phase0 = call_claude(PHASE0_PROMPT.format(text=text_truncated), anthropic_key)

        content_type = phase0.get("content_type", "misto")
        guiding_question = phase0.get("guiding_question", "")

        # ── FASE 1: Analisi calibrata ────────────────────────────────────────
        if content_type in PHASE1_PROMPTS:
            p1_prompt = PHASE1_PROMPTS[content_type].format(text=text_truncated)
        else:
            p1_prompt = PHASE1_DEFAULT.format(
                content_type=phase0.get("content_type_label", content_type),
                guiding_question=guiding_question,
                text=text_truncated
            )

        phase1 = call_claude(p1_prompt, anthropic_key)

        # ── FASE 2: Verifica fatti ───────────────────────────────────────────
        claims = phase1.get("claims", [])
        phase2 = {"verified_claims": [], "fact_check_summary": "", "most_problematic": "", "most_solid": ""}

        if claims:
            claims_for_check = [{"claim": c.get("claim", ""), "initial_verdict": c.get("verdict_label", "")} for c in claims[:5]]
            p2_prompt = PHASE2_PROMPT.format(
                claims_json=json.dumps(claims_for_check, ensure_ascii=False),
                content_type=phase0.get("content_type_label", content_type)
            )
            try:
                phase2 = call_claude_with_search(p2_prompt, anthropic_key)
            except Exception:
                try:
                    phase2 = call_claude(p2_prompt, anthropic_key)
                except Exception:
                    pass

        result = {
            "transcription": text[:500] + ("..." if len(text) > 500 else ""),
            "phase0": phase0,
            "phase1": phase1,
            "phase2": phase2
        }
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/analyze-live-chunk", methods=["POST"])
def analyze_live_chunk():
    data = request.json
    anthropic_key = data.get("anthropic_key") or ANTHROPIC_API_KEY
    text = data.get("text", "")
    chunk_num = data.get("chunk_num", 1)

    if not anthropic_key:
        return jsonify({"error": "Chiave API Anthropic mancante"}), 400
    if not text or len(text.strip()) < 10:
        return jsonify({"flags": [], "risk_level": "low", "risk_score": 0, "techniques": [], "summary": ""}), 200

    try:
        prompt = LIVE_CHUNK_PROMPT.format(chunk_num=chunk_num, text=text[:2000])
        result = call_claude(prompt, anthropic_key)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "2.0.0"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
