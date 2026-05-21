import os
import json
import tempfile
import subprocess
import threading
import time

try:
    subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
except Exception:
    subprocess.run(["apt-get", "install", "-y", "ffmpeg"], capture_output=True)

from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

ANALYSIS_PROMPT = """Sei un analista critico dei media esperto in fact-checking, retorica, psicologia della comunicazione e pensiero critico.
Analizza il seguente contenuto e restituisci SOLO un oggetto JSON valido, senza markdown, senza backtick.

TIPO DI CONTENUTO: {mode}
CONTENUTO:
\"\"\"{text}\"\"\"

Restituisci questo JSON (in italiano):
{{
  "risk_score_claims": <0-100>,
  "risk_score_framing": <0-100>,
  "risk_score_bias": <0-100>,
  "risk_score_rhetoric": <0-100>,
  "claims_level": "<Nessun claim|Basso|Moderato|Alto|Grave>",
  "claims_summary": "<paragrafo sui claim>",
  "claims": [
    {{
      "claim": "<citazione o parafrasi>",
      "verdict_label": "<Verificato|Parzialmente vero|Falso|Non verificabile>",
      "verdict_key": "<true|partial|false|unverifiable>",
      "color": "<green|yellow|red>",
      "explanation": "<spiegazione 1-2 frasi>"
    }}
  ],
  "framing_level": "<Assente|Basso|Moderato|Alto|Molto alto>",
  "framing_analysis": "<analisi framing, 2-3 frasi>",
  "framing_examples": "<esempi specifici dal testo>",
  "bias_level": "<Assente|Lieve|Moderato|Forte|Molto forte>",
  "bias_analysis": "<analisi bias, 2-3 frasi>",
  "bias_spectrum": "<posizionamento ideologico rilevato>",
  "rhetoric_level": "<Assente|Basso|Moderato|Alto|Molto alto>",
  "rhetoric_analysis": "<analisi tecniche retoriche, 2-3 frasi>",
  "rhetoric_techniques": ["<tecnica1>", "<tecnica2>"],
  "omissions_level": "<Nessuna|Poche|Alcune|Molte|Sistematiche>",
  "omissions_analysis": "<cosa viene taciuto, 2-3 frasi>",
  "omissions": ["<cosa manca 1>", "<cosa manca 2>"],
  "overall_verdict": "<verdetto complessivo 3-4 frasi>",
  "reader_advice": "<consiglio pratico 1-2 frasi>"
}}"""

LIVE_CHUNK_PROMPT = """Sei un analista critico dei media in tempo reale. Analizza questo frammento di testo parlato e restituisci SOLO JSON valido.

FRAMMENTO (chunk #{chunk_num}):
\"\"\"{text}\"\"\"

JSON richiesto:
{{
  "risk_level": "<low|medium|high>",
  "risk_score": <0-100>,
  "flags": [
    {{
      "type": "<claim|framing|rhetoric|bias>",
      "text": "<frase specifica dal testo>",
      "note": "<spiegazione breve>"
    }}
  ],
  "techniques": ["<tecnica retorica se presente>"],
  "summary": "<una frase su cosa sta succedendo in questo momento>"
}}"""


def call_claude(prompt, api_key):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01"
        },
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}]
        },
        timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
    raw = "".join(b.get("text", "") for b in data.get("content", []))
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
    tmpdir = tempfile.mkdtemp()
    out_path = os.path.join(tmpdir, "audio")
    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--no-playlist",
        "--max-filesize", "50m",
        "--ffmpeg-location", "/usr/bin",
        "-o", out_path + ".%(ext)s",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    for ext in ["mp3", "m4a", "webm", "opus", "ogg", "wav"]:
        candidate = out_path + "." + ext
        if os.path.exists(candidate):
            return candidate
    if result.returncode != 0:
        raise Exception(f"Download fallito: {result.stderr[:300]}")
    raise Exception("File audio non trovato dopo il download")


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
        if mode == "url" and url:
            if not openai_key:
                return jsonify({"error": "Chiave API OpenAI necessaria per analizzare video/audio"}), 400
            audio_path = download_audio(url)
            text = transcribe_with_whisper(audio_path, openai_key)
            try:
                os.remove(audio_path)
            except:
                pass

        if not text or len(text.strip()) < 20:
            return jsonify({"error": "Testo troppo breve o vuoto"}), 400

        mode_labels = {
            "text": "testo libero / post social",
            "url": "trascrizione video/audio",
            "transcript": "trascrizione podcast/dibattito",
            "article": "articolo / notizia",
            "live": "trascrizione live"
        }
        prompt = ANALYSIS_PROMPT.format(
            mode=mode_labels.get(mode, mode),
            text=text[:8000]
        )
        result = call_claude(prompt, anthropic_key)
        result["transcription"] = text[:500] + ("..." if len(text) > 500 else "")
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
    return jsonify({"status": "ok", "version": "1.0.0"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
