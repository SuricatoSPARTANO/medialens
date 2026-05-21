import os
import json
import tempfile
import subprocess
import re

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


def sanitize(text):
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u2013', '-').replace('\u2014', '-')
    return text[:8000]


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
            "max_tokens": 3000,
            "messages": [{"role": "user", "content": prompt}]
        },
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

    # Update yt-dlp
    subprocess.run(
        ["pip", "install", "--upgrade", "yt-dlp", "--break-system-packages"],
        capture_output=True, timeout=60
    )

    # Find JS runtime
    js_args = []
    for runtime in ["node", "nodejs", "deno"]:
        path = shutil.which(runtime)
        if path:
            js_args = ["--js-runtimes", f"{runtime}:{path}"]
            break

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--max-filesize", "50m",
        "--ffmpeg-location", "/usr/bin",
        "-f", "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
        "--no-check-certificate",
    ] + js_args + ["-o", out_path + ".%(ext)s", url]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    for ext in ["m4a", "mp3", "webm", "opus", "ogg", "wav", "mp4"]:
        candidate = out_path + "." + ext
        if os.path.exists(candidate):
            return candidate

    files = [f for f in os.listdir(tmpdir) if not f.endswith('.part')]
    if files:
        return os.path.join(tmpdir, files[0])

    raise Exception(f"Download fallito: {result.stderr[:400]}")


PHASE0_PROMPT = """Analizza il seguente contenuto e classificalo. Restituisci SOLO JSON valido senza markdown.

CONTENUTO:
'''{text}'''

JSON:
{{
  "content_type": "<informativo|politico|attivista|testimoniale|educativo|intrattenimento|commerciale|misto|complottista|satirico>",
  "content_type_label": "<nome leggibile italiano>",
  "intent": "<intento principale, 1 frase>",
  "target_audience": "<pubblico target, 1 frase>",
  "guiding_question": "<domanda critica principale, 1 frase>",
  "risk_profile": "<low|medium|high>",
  "classification_note": "<spiegazione classificazione, 2-3 frasi>"
}}"""

PHASE1_PROMPT = """Sei un analista critico dei media. Analizza questo contenuto di tipo {content_type}.
Domanda guida: {guiding_question}

IMPORTANTE: Per contenuti testimoniali/personali, l'emozione e' il mezzo espressivo legittimo - non penalizzarla come framing manipolativo. Concentrati solo su generalizzazioni indebite e claim universali non supportati.

CONTENUTO:
'''{text}'''

Restituisci SOLO JSON valido senza markdown:
{{
  "risk_score_claims": <0-100>,
  "risk_score_framing": <0-100>,
  "risk_score_bias": <0-100>,
  "risk_score_rhetoric": <0-100>,
  "claims_level": "<Nessun claim|Basso|Moderato|Alto|Grave>",
  "claims_summary": "<analisi claim>",
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

PHASE2_PROMPT = """Sei un fact-checker. Verifica ogni claim con ricerca web. Restituisci SOLO JSON valido senza markdown.

CLAIMS:
{claims_json}

TIPO CONTENUTO: {content_type}

{{
  "verified_claims": [
    {{
      "claim": "<testo>",
      "verdict": "<Vero|Parzialmente vero|Falso|Non verificabile|Opinione>",
      "verdict_key": "<true|partial|false|unverifiable|opinion>",
      "confidence": "<Alta|Media|Bassa>",
      "explanation": "<spiegazione con dettagli, 2-3 frasi>",
      "sources": ["<fonte>"],
      "color": "<green|yellow|red>"
    }}
  ],
  "fact_check_summary": "<sintesi verifica, 2-3 frasi>",
  "most_problematic": "<claim piu problematico>",
  "most_solid": "<claim piu solido>"
}}"""

LIVE_PROMPT = """Analizza questo frammento parlato. SOLO JSON valido.
FRAMMENTO #{chunk_num}: '''{text}'''
{{"risk_level":"<low|medium|high>","risk_score":<0-100>,"flags":[{{"type":"<claim|framing|rhetoric|bias>","text":"<frase>","note":"<spiegazione>"}}],"techniques":["<tecnica>"],"summary":"<una frase>"}}"""


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
                return jsonify({"error": "Chiave API OpenAI necessaria per video/audio"}), 400
            audio_path = download_audio(url)
            text = transcribe_with_whisper(audio_path, openai_key)
            try:
                os.remove(audio_path)
            except Exception:
                pass

        if not text or len(text.strip()) < 20:
            return jsonify({"error": "Testo troppo breve o vuoto"}), 400

        text_clean = sanitize(text)

        # Phase 0
        p0 = call_claude(PHASE0_PROMPT.format(text=text_clean), anthropic_key)
        content_type = p0.get("content_type_label", p0.get("content_type", "generico"))
        guiding_q = p0.get("guiding_question", "")

        # Phase 1
        p1 = call_claude(PHASE1_PROMPT.format(
            content_type=content_type,
            guiding_question=guiding_q,
            text=text_clean
        ), anthropic_key)

        # Phase 2
        claims = p1.get("claims", [])
        p2 = {"verified_claims": [], "fact_check_summary": "", "most_problematic": "", "most_solid": ""}
        if claims:
            claims_short = [{"claim": c.get("claim", ""), "verdict_iniziale": c.get("verdict_label", "")} for c in claims[:5]]
            try:
                p2 = call_claude(PHASE2_PROMPT.format(
                    claims_json=json.dumps(claims_short, ensure_ascii=False),
                    content_type=content_type
                ), anthropic_key)
            except Exception:
                pass

        return jsonify({
            "transcription": text[:500] + ("..." if len(text) > 500 else ""),
            "phase0": p0,
            "phase1": p1,
            "phase2": p2
        })

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
        result = call_claude(LIVE_PROMPT.format(chunk_num=chunk_num, text=text[:2000]), anthropic_key)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "2.0.0"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


# ─── DEBATE MODE ─────────────────────────────────────────────────────────────

DEBATE_TURN_PROMPT = """Sei l'AI moderatrice di un dibattito in tempo reale. Analizza questo intervento.

ARGOMENTO DEL DIBATTITO: {topic}
OBIETTIVO: {objective}
PARTECIPANTE: {speaker}
INTERVENTO: '''{text}'''

STORICO DIBATTITO (ultimi interventi):
{history}

Restituisci SOLO JSON valido:
{{
  "claims": [
    {{
      "text": "<claim specifico>",
      "verdict": "<Verificato|Parzialmente vero|Falso|Non verificabile|Opinione>",
      "verdict_key": "<true|partial|false|unverifiable|opinion>",
      "explanation": "<spiegazione breve>"
    }}
  ],
  "rhetoric_techniques": ["<tecnica se presente>"],
  "argument_strength": <0-100>,
  "argument_note": "<valutazione breve della solidità dell'argomento, 1 frase>",
  "moderator_question": "<domanda dell'AI per approfondire o sfidare, 1 frase>",
  "flag": "<none|weak_argument|false_claim|good_point|rhetorical_trick>",
  "flag_label": "<etichetta leggibile del flag>"
}}"""

DEBATE_FINAL_PROMPT = """Sei l'AI moderatrice. Il dibattito è terminato. Genera il report finale.

ARGOMENTO: {topic}
OBIETTIVO SCELTO: {objective}
PARTECIPANTI: {participants}

TRASCRIZIONE COMPLETA:
{transcript}

ANALISI DEGLI INTERVENTI:
{analyses}

Restituisci SOLO JSON valido:
{{
  "winner_facts": "<chi aveva più ragione sui fatti, con motivazione>",
  "critical_thinking_notes": [{{"speaker": "<nome>", "note": "<valutazione pensiero critico>"}}],
  "shared_ground": "<punti di accordo emersi, anche impliciti>",
  "position_summary": [{{"speaker": "<nome>", "position": "<sintesi posizione>", "strongest_point": "<argomento più solido>", "weakest_point": "<argomento più debole>"}}],
  "key_claims_verified": [{{"claim": "<testo>", "verdict": "<verdetto>", "speaker": "<chi l'ha detto>"}}],
  "overall_quality": "<valutazione complessiva della qualità del dibattito, 2-3 frasi>",
  "next_questions": ["<domanda aperta rimasta senza risposta>"]
}}"""


@app.route("/api/debate/turn", methods=["POST"])
def debate_turn():
    data = request.json
    anthropic_key = data.get("anthropic_key") or ANTHROPIC_API_KEY
    if not anthropic_key:
        return jsonify({"error": "Chiave API Anthropic mancante"}), 400

    text = sanitize(data.get("text", ""))
    speaker = data.get("speaker", "Partecipante")
    topic = data.get("topic", "")
    objective = data.get("objective", "")
    history = data.get("history", "")

    if not text or len(text.strip()) < 5:
        return jsonify({"error": "Intervento troppo breve"}), 400

    try:
        prompt = DEBATE_TURN_PROMPT.format(
            topic=topic,
            objective=objective,
            speaker=speaker,
            text=text,
            history=history[-3000:] if history else "Nessuno ancora"
        )
        result = call_claude(prompt, anthropic_key)
        result["speaker"] = speaker
        result["text"] = text
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/debate/final", methods=["POST"])
def debate_final():
    data = request.json
    anthropic_key = data.get("anthropic_key") or ANTHROPIC_API_KEY
    if not anthropic_key:
        return jsonify({"error": "Chiave API Anthropic mancante"}), 400

    try:
        prompt = DEBATE_FINAL_PROMPT.format(
            topic=data.get("topic", ""),
            objective=data.get("objective", ""),
            participants=", ".join(data.get("participants", [])),
            transcript=sanitize(data.get("transcript", "")),
            analyses=json.dumps(data.get("analyses", [])[:20], ensure_ascii=False)[:4000]
        )
        result = call_claude(prompt, anthropic_key)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/debate")
def debate_page():
    from flask import Response
    import pathlib
    base = pathlib.Path(__file__).parent
    html = (base / "templates" / "debate.html").read_text(encoding="utf-8")
    return Response(html, mimetype="text/html")
