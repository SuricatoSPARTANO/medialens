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


DEBATE_HTML = __import__('base64').b64decode("PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9Iml0Ij4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9IlVURi04Ij4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCwgaW5pdGlhbC1zY2FsZT0xLjAiPgo8dGl0bGU+TWVkaWEgTGVucyDigJQgQXJlbmEgRGliYXR0aXRvPC90aXRsZT4KPHN0eWxlPgo6cm9vdCB7CiAgLS1iZzogIzBhMGEwZjsKICAtLXN1cmZhY2U6ICMxMzEzMWE7CiAgLS1zdXJmYWNlMjogIzFhMWEyNDsKICAtLWJvcmRlcjogcmdiYSgyNTUsMjU1LDI1NSwwLjA4KTsKICAtLWJvcmRlcjI6IHJnYmEoMjU1LDI1NSwyNTUsMC4xNCk7CiAgLS10ZXh0OiAjZjBmMGY1OwogIC0tbXV0ZWQ6ICM4ODg4YTA7CiAgLS1oaW50OiAjNGE0YTYwOwogIC0tYWNjZW50OiAjZTk0NTYwOwogIC0tb2s6ICMyMmM1NWU7CiAgLS13YXJuOiAjZjU5ZTBiOwogIC0taW5mbzogIzM4YmRmODsKICAtLXB1cnBsZTogIzdjNmFmNzsKICAtLWZvbnQ6IC1hcHBsZS1zeXN0ZW0sIEJsaW5rTWFjU3lzdGVtRm9udCwgJ1NlZ29lIFVJJywgSGVsdmV0aWNhLCBBcmlhbCwgc2Fucy1zZXJpZjsKICAtLW1vbm86ICdTRiBNb25vJywgJ01vbmFjbycsICdDb25zb2xhcycsIG1vbm9zcGFjZTsKfQoqIHsgYm94LXNpemluZzogYm9yZGVyLWJveDsgbWFyZ2luOiAwOyBwYWRkaW5nOiAwOyB9CmJvZHkgeyBiYWNrZ3JvdW5kOiB2YXIoLS1iZyk7IGNvbG9yOiB2YXIoLS10ZXh0KTsgZm9udC1mYW1pbHk6IHZhcigtLWZvbnQpOyBtaW4taGVpZ2h0OiAxMDB2aDsgfQouc2hlbGwgeyBtYXgtd2lkdGg6IDEwMDBweDsgbWFyZ2luOiAwIGF1dG87IHBhZGRpbmc6IDAgMjBweCA4MHB4OyB9CgpoZWFkZXIgeyBwYWRkaW5nOiAyNHB4IDAgMjBweDsgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6IGNlbnRlcjsgZ2FwOiAxMnB4OyBib3JkZXItYm90dG9tOiAwLjVweCBzb2xpZCB2YXIoLS1ib3JkZXIpOyBtYXJnaW4tYm90dG9tOiAyOHB4OyB9Ci5sb2dvIHsgd2lkdGg6IDM2cHg7IGhlaWdodDogMzZweDsgYmFja2dyb3VuZDogdmFyKC0tcHVycGxlKTsgYm9yZGVyLXJhZGl1czogOHB4OyBkaXNwbGF5OiBmbGV4OyBhbGlnbi1pdGVtczogY2VudGVyOyBqdXN0aWZ5LWNvbnRlbnQ6IGNlbnRlcjsgZm9udC1zaXplOiAxOHB4OyB9Ci5icmFuZCBoMSB7IGZvbnQtc2l6ZTogMThweDsgZm9udC13ZWlnaHQ6IDYwMDsgfQouYnJhbmQgcCB7IGZvbnQtc2l6ZTogMTJweDsgY29sb3I6IHZhcigtLW11dGVkKTsgfQouYmFjay1idG4geyBtYXJnaW4tbGVmdDogYXV0bzsgcGFkZGluZzogNnB4IDE0cHg7IGJvcmRlcjogMC41cHggc29saWQgdmFyKC0tYm9yZGVyMik7IGJvcmRlci1yYWRpdXM6IDZweDsgYmFja2dyb3VuZDogdmFyKC0tc3VyZmFjZSk7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGZvbnQtc2l6ZTogMTJweDsgY3Vyc29yOiBwb2ludGVyOyB0ZXh0LWRlY29yYXRpb246IG5vbmU7IH0KCi8qIFNFVFVQICovCiNzZXR1cFNjcmVlbiB7IGRpc3BsYXk6IGJsb2NrOyB9CiNkZWJhdGVTY3JlZW4geyBkaXNwbGF5OiBub25lOyB9CiNyZXBvcnRTY3JlZW4geyBkaXNwbGF5OiBub25lOyB9Cgouc2V0dXAtY2FyZCB7IGJhY2tncm91bmQ6IHZhcigtLXN1cmZhY2UpOyBib3JkZXI6IDAuNXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IGJvcmRlci1yYWRpdXM6IDE0cHg7IHBhZGRpbmc6IDI0cHg7IG1hcmdpbi1ib3R0b206IDE2cHg7IH0KLnNldHVwLWNhcmQgaDIgeyBmb250LXNpemU6IDE1cHg7IGZvbnQtd2VpZ2h0OiA1MDA7IG1hcmdpbi1ib3R0b206IDE2cHg7IGNvbG9yOiB2YXIoLS10ZXh0KTsgfQouZmllbGQgbGFiZWwgeyBmb250LXNpemU6IDEycHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGRpc3BsYXk6IGJsb2NrOyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KLmZpZWxkIGlucHV0LCAuZmllbGQgdGV4dGFyZWEsIC5maWVsZCBzZWxlY3QgeyB3aWR0aDogMTAwJTsgYmFja2dyb3VuZDogdmFyKC0tc3VyZmFjZTIpOyBib3JkZXI6IDAuNXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpOyBib3JkZXItcmFkaXVzOiA4cHg7IHBhZGRpbmc6IDEwcHggMTJweDsgY29sb3I6IHZhcigtLXRleHQpOyBmb250LWZhbWlseTogdmFyKC0tZm9udCk7IGZvbnQtc2l6ZTogMTRweDsgb3V0bGluZTogbm9uZTsgfQouZmllbGQgaW5wdXQ6Zm9jdXMsIC5maWVsZCBzZWxlY3Q6Zm9jdXMgeyBib3JkZXItY29sb3I6IHZhcigtLXB1cnBsZSk7IH0KLmZpZWxkIHsgbWFyZ2luLWJvdHRvbTogMTRweDsgfQoKLnBhcnRpY2lwYW50cy1saXN0IHsgZGlzcGxheTogZmxleDsgZmxleC1kaXJlY3Rpb246IGNvbHVtbjsgZ2FwOiA4cHg7IG1hcmdpbi1ib3R0b206IDEycHg7IH0KLnBhcnRpY2lwYW50LXJvdyB7IGRpc3BsYXk6IGZsZXg7IGdhcDogOHB4OyBhbGlnbi1pdGVtczogY2VudGVyOyB9Ci5wYXJ0aWNpcGFudC1yb3cgaW5wdXQgeyBmbGV4OiAxOyB9Ci5jb2xvci1kb3QgeyB3aWR0aDogMjRweDsgaGVpZ2h0OiAyNHB4OyBib3JkZXItcmFkaXVzOiA1MCU7IGZsZXgtc2hyaW5rOiAwOyBjdXJzb3I6IHBvaW50ZXI7IGJvcmRlcjogMnB4IHNvbGlkIHRyYW5zcGFyZW50OyB9Ci5jb2xvci1kb3Quc2VsZWN0ZWQgeyBib3JkZXItY29sb3I6ICNmZmY7IH0KLmJ0bi1hZGQgeyBwYWRkaW5nOiA4cHggMTZweDsgYm9yZGVyOiAwLjVweCBkYXNoZWQgdmFyKC0tYm9yZGVyMik7IGJvcmRlci1yYWRpdXM6IDhweDsgYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGZvbnQtc2l6ZTogMTNweDsgY3Vyc29yOiBwb2ludGVyOyB3aWR0aDogMTAwJTsgfQouYnRuLWFkZDpob3ZlciB7IGJvcmRlci1jb2xvcjogdmFyKC0tcHVycGxlKTsgY29sb3I6IHZhcigtLXB1cnBsZSk7IH0KLmJ0bi1yZW1vdmUgeyB3aWR0aDogMjhweDsgaGVpZ2h0OiAyOHB4OyBib3JkZXI6IDAuNXB4IHNvbGlkIHZhcigtLWJvcmRlcjIpOyBib3JkZXItcmFkaXVzOiA2cHg7IGJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjogdmFyKC0tbXV0ZWQpOyBjdXJzb3I6IHBvaW50ZXI7IGZvbnQtc2l6ZTogMTZweDsgZmxleC1zaHJpbms6IDA7IH0KCi5vYmplY3RpdmUtZ3JpZCB7IGRpc3BsYXk6IGdyaWQ7IGdyaWQtdGVtcGxhdGUtY29sdW1uczogMWZyIDFmcjsgZ2FwOiA4cHg7IH0KLm9iai1idG4geyBwYWRkaW5nOiAxMnB4IDE0cHg7IGJvcmRlcjogMC41cHggc29saWQgdmFyKC0tYm9yZGVyMik7IGJvcmRlci1yYWRpdXM6IDEwcHg7IGJhY2tncm91bmQ6IHZhcigtLXN1cmZhY2UyKTsgY29sb3I6IHZhcigtLW11dGVkKTsgZm9udC1zaXplOiAxM3B4OyBjdXJzb3I6IHBvaW50ZXI7IHRleHQtYWxpZ246IGxlZnQ7IGZvbnQtZmFtaWx5OiB2YXIoLS1mb250KTsgdHJhbnNpdGlvbjogYWxsIC4xNXM7IH0KLm9iai1idG46aG92ZXIgeyBib3JkZXItY29sb3I6IHZhcigtLXB1cnBsZSk7IGNvbG9yOiB2YXIoLS10ZXh0KTsgfQoub2JqLWJ0bi5zZWwgeyBib3JkZXItY29sb3I6IHZhcigtLXB1cnBsZSk7IGJhY2tncm91bmQ6IHJnYmEoMTI0LDEwNiwyNDcsLjEpOyBjb2xvcjogdmFyKC0tcHVycGxlKTsgfQoub2JqLWJ0biAub2JqLWljb24geyBmb250LXNpemU6IDIwcHg7IGRpc3BsYXk6IGJsb2NrOyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KLm9iai1idG4gLm9iai1sYWJlbCB7IGZvbnQtd2VpZ2h0OiA1MDA7IGRpc3BsYXk6IGJsb2NrOyB9Ci5vYmotYnRuIC5vYmotZGVzYyB7IGZvbnQtc2l6ZTogMTFweDsgY29sb3I6IHZhcigtLW11dGVkKTsgbWFyZ2luLXRvcDogM3B4OyBkaXNwbGF5OiBibG9jazsgfQoKLmFwaS1yb3cgeyBkaXNwbGF5OiBmbGV4OyBnYXA6IDhweDsgfQouYXBpLXJvdyBpbnB1dCB7IGZsZXg6IDE7IGZvbnQtZmFtaWx5OiB2YXIoLS1tb25vKTsgZm9udC1zaXplOiAxMnB4OyB9CgouYnRuLXN0YXJ0IHsgd2lkdGg6IDEwMCU7IHBhZGRpbmc6IDE0cHg7IGJhY2tncm91bmQ6IHZhcigtLXB1cnBsZSk7IGNvbG9yOiAjZmZmOyBib3JkZXI6IG5vbmU7IGJvcmRlci1yYWRpdXM6IDEwcHg7IGZvbnQtc2l6ZTogMTVweDsgZm9udC13ZWlnaHQ6IDUwMDsgY3Vyc29yOiBwb2ludGVyOyBmb250LWZhbWlseTogdmFyKC0tZm9udCk7IG1hcmdpbi10b3A6IDhweDsgfQouYnRuLXN0YXJ0OmhvdmVyIHsgb3BhY2l0eTogLjg1OyB9Ci5idG4tc3RhcnQ6ZGlzYWJsZWQgeyBvcGFjaXR5OiAuNDsgY3Vyc29yOiBub3QtYWxsb3dlZDsgfQoKLyogREVCQVRFICovCi5kZWJhdGUtaGVhZGVyIHsgZGlzcGxheTogZmxleDsgYWxpZ24taXRlbXM6IGNlbnRlcjsgZ2FwOiAxMnB4OyBtYXJnaW4tYm90dG9tOiAyMHB4OyBwYWRkaW5nOiAxNHB4IDE4cHg7IGJhY2tncm91bmQ6IHZhcigtLXN1cmZhY2UpOyBib3JkZXItcmFkaXVzOiAxMnB4OyBib3JkZXI6IDAuNXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IH0KLmRlYmF0ZS10b3BpYyB7IGZsZXg6IDE7IH0KLmRlYmF0ZS10b3BpYyAudG9waWMtbGFiZWwgeyBmb250LXNpemU6IDExcHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IHRleHQtdHJhbnNmb3JtOiB1cHBlcmNhc2U7IGxldHRlci1zcGFjaW5nOiAuMDZlbTsgfQouZGViYXRlLXRvcGljIC50b3BpYy10ZXh0IHsgZm9udC1zaXplOiAxNHB4OyBmb250LXdlaWdodDogNTAwOyBtYXJnaW4tdG9wOiAycHg7IH0KLnR1cm4tY291bnRlciB7IGZvbnQtc2l6ZTogMTJweDsgY29sb3I6IHZhcigtLW11dGVkKTsgZm9udC1mYW1pbHk6IHZhcigtLW1vbm8pOyB9Ci5idG4tZW5kIHsgcGFkZGluZzogOHB4IDE2cHg7IGJvcmRlcjogMC41cHggc29saWQgcmdiYSgyMzMsNjksOTYsLjQpOyBib3JkZXItcmFkaXVzOiA4cHg7IGJhY2tncm91bmQ6IHJnYmEoMjMzLDY5LDk2LC4wOCk7IGNvbG9yOiB2YXIoLS1hY2NlbnQpOyBmb250LXNpemU6IDEzcHg7IGN1cnNvcjogcG9pbnRlcjsgZm9udC1mYW1pbHk6IHZhcigtLWZvbnQpOyB9CgouZGViYXRlLWxheW91dCB7IGRpc3BsYXk6IGdyaWQ7IGdyaWQtdGVtcGxhdGUtY29sdW1uczogMWZyIDMyMHB4OyBnYXA6IDE2cHg7IH0KCi5zcGVha2Vycy1hcmVhIHsgZGlzcGxheTogZmxleDsgZmxleC1kaXJlY3Rpb246IGNvbHVtbjsgZ2FwOiAxMHB4OyB9Ci5zcGVha2VyLWJ0biB7IHBhZGRpbmc6IDE0cHggMThweDsgYm9yZGVyLXJhZGl1czogMTJweDsgYm9yZGVyOiAycHggc29saWQgdHJhbnNwYXJlbnQ7IGJhY2tncm91bmQ6IHZhcigtLXN1cmZhY2UpOyBjdXJzb3I6IHBvaW50ZXI7IGZvbnQtZmFtaWx5OiB2YXIoLS1mb250KTsgdHJhbnNpdGlvbjogYWxsIC4xNXM7IHRleHQtYWxpZ246IGxlZnQ7IHBvc2l0aW9uOiByZWxhdGl2ZTsgfQouc3BlYWtlci1idG46aG92ZXIgeyBvcGFjaXR5OiAuOTsgfQouc3BlYWtlci1idG4uYWN0aXZlIHsgdHJhbnNmb3JtOiBzY2FsZSgxLjAxKTsgfQouc3BlYWtlci1idG4ucmVjb3JkaW5nIHsgYW5pbWF0aW9uOiByZWNvcmRQdWxzZSAxcyBpbmZpbml0ZTsgfQpAa2V5ZnJhbWVzIHJlY29yZFB1bHNlIHsgMCUsMTAwJXtvcGFjaXR5OjF9IDUwJXtvcGFjaXR5Oi43fSB9Ci5zcGVha2VyLW5hbWUgeyBmb250LXNpemU6IDE1cHg7IGZvbnQtd2VpZ2h0OiA2MDA7IGNvbG9yOiAjZmZmOyB9Ci5zcGVha2VyLXNjb3JlIHsgZm9udC1zaXplOiAxMnB4OyBvcGFjaXR5OiAuODsgbWFyZ2luLXRvcDogMnB4OyB9Ci5zcGVha2VyLXRyYW5zY3JpcHQgeyBmb250LXNpemU6IDEycHg7IGNvbG9yOiByZ2JhKDI1NSwyNTUsMjU1LC43KTsgbWFyZ2luLXRvcDogOHB4OyBmb250LXN0eWxlOiBpdGFsaWM7IG1pbi1oZWlnaHQ6IDE4cHg7IH0KLnJlYy1pbmRpY2F0b3IgeyBwb3NpdGlvbjogYWJzb2x1dGU7IHRvcDogMTJweDsgcmlnaHQ6IDE0cHg7IHdpZHRoOiAxMHB4OyBoZWlnaHQ6IDEwcHg7IGJvcmRlci1yYWRpdXM6IDUwJTsgYmFja2dyb3VuZDogdmFyKC0tYWNjZW50KTsgZGlzcGxheTogbm9uZTsgfQoucmVjLWluZGljYXRvci5vbiB7IGRpc3BsYXk6IGJsb2NrOyBhbmltYXRpb246IHB1bHNlIDFzIGluZmluaXRlOyB9CkBrZXlmcmFtZXMgcHVsc2UgeyAwJSwxMDAle29wYWNpdHk6MX0gNTAle29wYWNpdHk6LjN9IH0KLnNwZWFrZXItc3RvcCB7IG1hcmdpbi10b3A6IDEwcHg7IHBhZGRpbmc6IDdweCAxNHB4OyBib3JkZXI6IDAuNXB4IHNvbGlkIHJnYmEoMjU1LDI1NSwyNTUsLjMpOyBib3JkZXItcmFkaXVzOiA2cHg7IGJhY2tncm91bmQ6IHJnYmEoMCwwLDAsLjIpOyBjb2xvcjogI2ZmZjsgZm9udC1zaXplOiAxMnB4OyBjdXJzb3I6IHBvaW50ZXI7IGRpc3BsYXk6IG5vbmU7IH0KLnNwZWFrZXItc3RvcC5zaG93IHsgZGlzcGxheTogaW5saW5lLWJsb2NrOyB9CgouYWktcGFuZWwgeyBkaXNwbGF5OiBmbGV4OyBmbGV4LWRpcmVjdGlvbjogY29sdW1uOyBnYXA6IDEwcHg7IH0KLmFpLXBhbmVsLXRpdGxlIHsgZm9udC1zaXplOiAxMnB4OyBjb2xvcjogdmFyKC0tbXV0ZWQpOyB0ZXh0LXRyYW5zZm9ybTogdXBwZXJjYXNlOyBsZXR0ZXItc3BhY2luZzogLjA2ZW07IG1hcmdpbi1ib3R0b206IDRweDsgfQoKLmFpLWZsYWcgeyBwYWRkaW5nOiAxMHB4IDEycHg7IGJvcmRlci1yYWRpdXM6IDhweDsgYm9yZGVyLWxlZnQ6IDNweCBzb2xpZCB0cmFuc3BhcmVudDsgYmFja2dyb3VuZDogdmFyKC0tc3VyZmFjZSk7IGZvbnQtc2l6ZTogMTJweDsgfQouYWktZmxhZy5ub25lIHsgYm9yZGVyLWxlZnQtY29sb3I6IHZhcigtLW9rKTsgfQouYWktZmxhZy5nb29kX3BvaW50IHsgYm9yZGVyLWxlZnQtY29sb3I6IHZhcigtLW9rKTsgfQouYWktZmxhZy53ZWFrX2FyZ3VtZW50IHsgYm9yZGVyLWxlZnQtY29sb3I6IHZhcigtLXdhcm4pOyB9Ci5haS1mbGFnLmZhbHNlX2NsYWltIHsgYm9yZGVyLWxlZnQtY29sb3I6IHZhcigtLWFjY2VudCk7IH0KLmFpLWZsYWcucmhldG9yaWNhbF90cmljayB7IGJvcmRlci1sZWZ0LWNvbG9yOiB2YXIoLS1pbmZvKTsgfQouZmxhZy1zcGVha2VyIHsgZm9udC13ZWlnaHQ6IDYwMDsgZm9udC1zaXplOiAxMXB4OyBtYXJnaW4tYm90dG9tOiA0cHg7IH0KLmZsYWctdGV4dCB7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGxpbmUtaGVpZ2h0OiAxLjU7IH0KLmZsYWctcXVlc3Rpb24geyBtYXJnaW4tdG9wOiA2cHg7IHBhZGRpbmc6IDZweCAxMHB4OyBiYWNrZ3JvdW5kOiByZ2JhKDEyNCwxMDYsMjQ3LC4xKTsgYm9yZGVyLXJhZGl1czogNnB4OyBmb250LXNpemU6IDExcHg7IGNvbG9yOiB2YXIoLS1wdXJwbGUpOyBmb250LXN0eWxlOiBpdGFsaWM7IH0KCi5zY29yZXMtcGFuZWwgeyBiYWNrZ3JvdW5kOiB2YXIoLS1zdXJmYWNlKTsgYm9yZGVyLXJhZGl1czogMTBweDsgcGFkZGluZzogMTJweCAxNHB4OyB9Ci5zY29yZS1yb3cgeyBkaXNwbGF5OiBmbGV4OyBhbGlnbi1pdGVtczogY2VudGVyOyBnYXA6IDhweDsgbWFyZ2luLWJvdHRvbTogOHB4OyB9Ci5zY29yZS1yb3c6bGFzdC1jaGlsZCB7IG1hcmdpbi1ib3R0b206IDA7IH0KLnNjb3JlLW5hbWUgeyBmb250LXNpemU6IDEycHg7IGZsZXg6IDE7IH0KLnNjb3JlLWJhci1iZyB7IGZsZXg6IDI7IGhlaWdodDogNnB4OyBiYWNrZ3JvdW5kOiB2YXIoLS1zdXJmYWNlMik7IGJvcmRlci1yYWRpdXM6IDNweDsgb3ZlcmZsb3c6IGhpZGRlbjsgfQouc2NvcmUtYmFyLWZpbGwgeyBoZWlnaHQ6IDEwMCU7IGJvcmRlci1yYWRpdXM6IDNweDsgdHJhbnNpdGlvbjogd2lkdGggLjVzOyB9Ci5zY29yZS12YWwgeyBmb250LXNpemU6IDExcHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGZvbnQtZmFtaWx5OiB2YXIoLS1tb25vKTsgbWluLXdpZHRoOiAyOHB4OyB0ZXh0LWFsaWduOiByaWdodDsgfQoKLmZlZWQgeyBiYWNrZ3JvdW5kOiB2YXIoLS1zdXJmYWNlKTsgYm9yZGVyLXJhZGl1czogMTBweDsgcGFkZGluZzogMTJweDsgbWF4LWhlaWdodDogMzAwcHg7IG92ZXJmbG93LXk6IGF1dG87IH0KLmZlZWQtaXRlbSB7IHBhZGRpbmc6IDhweCAxMHB4OyBib3JkZXItcmFkaXVzOiA4cHg7IG1hcmdpbi1ib3R0b206IDZweDsgYm9yZGVyLWxlZnQ6IDNweCBzb2xpZCB0cmFuc3BhcmVudDsgfQouZmVlZC1pdGVtLXNwZWFrZXIgeyBmb250LXNpemU6IDExcHg7IGZvbnQtd2VpZ2h0OiA2MDA7IG1hcmdpbi1ib3R0b206IDNweDsgfQouZmVlZC1pdGVtLXRleHQgeyBmb250LXNpemU6IDEycHg7IGNvbG9yOiB2YXIoLS1tdXRlZCk7IGxpbmUtaGVpZ2h0OiAxLjQ7IH0KLmZlZWQtaXRlbS1tZXRhIHsgZm9udC1zaXplOiAxMHB4OyBjb2xvcjogdmFyKC0taGludCk7IG1hcmdpbi10b3A6IDRweDsgfQoKLyogUkVQT1JUICovCi5yZXBvcnQtc2VjdGlvbiB7IGJhY2tncm91bmQ6IHZhcigtLXN1cmZhY2UpOyBib3JkZXI6IDAuNXB4IHNvbGlkIHZhcigtLWJvcmRlcik7IGJvcmRlci1yYWRpdXM6IDEycHg7IHBhZGRpbmc6IDE4cHg7IG1hcmdpbi1ib3R0b206IDEycHg7IH0KLnJlcG9ydC1zZWN0aW9uIGgzIHsgZm9udC1zaXplOiAxNHB4OyBmb250LXdlaWdodDogNTAwOyBtYXJnaW4tYm90dG9tOiAxMnB4OyBkaXNwbGF5OiBmbGV4OyBhbGlnbi1pdGVtczogY2VudGVyOyBnYXA6IDhweDsgfQoucG9zaXRpb24tY2FyZCB7IHBhZGRpbmc6IDEycHggMTRweDsgYmFja2dyb3VuZDogdmFyKC0tc3VyZmFjZTIpOyBib3JkZXItcmFkaXVzOiAxMHB4OyBib3JkZXItbGVmdDogNHB4IHNvbGlkIHRyYW5zcGFyZW50OyBtYXJnaW4tYm90dG9tOiA4cHg7IH0KLnBvcy1zcGVha2VyIHsgZm9udC1zaXplOiAxM3B4OyBmb250LXdlaWdodDogNjAwOyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KLnBvcy1wb3NpdGlvbiB7IGZvbnQtc2l6ZTogMTJweDsgY29sb3I6IHZhcigtLW11dGVkKTsgbWFyZ2luLWJvdHRvbTogOHB4OyBsaW5lLWhlaWdodDogMS41OyB9Ci5wb3Mtc3Ryb25nIHsgZm9udC1zaXplOiAxMXB4OyBjb2xvcjogdmFyKC0tb2spOyB9Ci5wb3Mtd2VhayB7IGZvbnQtc2l6ZTogMTFweDsgY29sb3I6IHZhcigtLWFjY2VudCk7IG1hcmdpbi10b3A6IDNweDsgfQoubmV4dC1xIHsgcGFkZGluZzogOHB4IDEycHg7IGJhY2tncm91bmQ6IHJnYmEoMTI0LDEwNiwyNDcsLjA4KTsgYm9yZGVyLXJhZGl1czogOHB4OyBmb250LXNpemU6IDEzcHg7IGNvbG9yOiB2YXIoLS1wdXJwbGUpOyBtYXJnaW4tYm90dG9tOiA2cHg7IH0KCi5zcGlubmVyIHsgZGlzcGxheTogaW5saW5lLWJsb2NrOyB3aWR0aDogMTRweDsgaGVpZ2h0OiAxNHB4OyBib3JkZXI6IDJweCBzb2xpZCByZ2JhKDI1NSwyNTUsMjU1LC4zKTsgYm9yZGVyLXRvcC1jb2xvcjogI2ZmZjsgYm9yZGVyLXJhZGl1czogNTAlOyBhbmltYXRpb246IHNwaW4gLjdzIGxpbmVhciBpbmZpbml0ZTsgfQpAa2V5ZnJhbWVzIHNwaW4geyB0byB7IHRyYW5zZm9ybTogcm90YXRlKDM2MGRlZyk7IH0gfQoKLmVycm9yLWJveCB7IGJhY2tncm91bmQ6IHJnYmEoMjMzLDY5LDk2LC4xKTsgYm9yZGVyOiAwLjVweCBzb2xpZCByZ2JhKDIzMyw2OSw5NiwuMyk7IGJvcmRlci1yYWRpdXM6IDEwcHg7IHBhZGRpbmc6IDEycHggMTZweDsgZm9udC1zaXplOiAxM3B4OyBjb2xvcjogI2YwOTU5NTsgbWFyZ2luLWJvdHRvbTogMTJweDsgZGlzcGxheTogbm9uZTsgfQouZXJyb3ItYm94LnNob3cgeyBkaXNwbGF5OiBibG9jazsgfQoKQG1lZGlhIChtYXgtd2lkdGg6IDcwMHB4KSB7CiAgLmRlYmF0ZS1sYXlvdXQgeyBncmlkLXRlbXBsYXRlLWNvbHVtbnM6IDFmcjsgfQogIC5vYmplY3RpdmUtZ3JpZCB7IGdyaWQtdGVtcGxhdGUtY29sdW1uczogMWZyOyB9Cn0KPC9zdHlsZT4KPC9oZWFkPgo8Ym9keT4KPGRpdiBjbGFzcz0ic2hlbGwiPgoKPGhlYWRlcj4KICA8ZGl2IGNsYXNzPSJsb2dvIj7impTvuI88L2Rpdj4KICA8ZGl2IGNsYXNzPSJicmFuZCI+CiAgICA8aDE+TWVkaWEgTGVucyDigJQgQXJlbmEgRGliYXR0aXRvPC9oMT4KICAgIDxwPkRpYmF0dGl0byBhdW1lbnRhdG8gZGFsbCdBSSBpbiB0ZW1wbyByZWFsZTwvcD4KICA8L2Rpdj4KICA8YSBocmVmPSIvIiBjbGFzcz0iYmFjay1idG4iPuKGkCBNZWRpYSBMZW5zPC9hPgo8L2hlYWRlcj4KCjxkaXYgY2xhc3M9ImVycm9yLWJveCIgaWQ9ImVycm9yQm94Ij48L2Rpdj4KCjwhLS0g4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQIFNFVFVQIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkCAtLT4KPGRpdiBpZD0ic2V0dXBTY3JlZW4iPgoKICA8ZGl2IGNsYXNzPSJzZXR1cC1jYXJkIj4KICAgIDxoMj7wn5SRIENoaWF2ZSBBUEk8L2gyPgogICAgPGRpdiBjbGFzcz0iZmllbGQiPgogICAgICA8bGFiZWw+QW50aHJvcGljIEFQSSBLZXk8L2xhYmVsPgogICAgICA8aW5wdXQgdHlwZT0icGFzc3dvcmQiIGlkPSJhcGlLZXkiIHBsYWNlaG9sZGVyPSJzay1hbnQtLi4uIiAvPgogICAgPC9kaXY+CiAgPC9kaXY+CgogIDxkaXYgY2xhc3M9InNldHVwLWNhcmQiPgogICAgPGgyPvCfkqwgQXJnb21lbnRvIGRlbCBkaWJhdHRpdG88L2gyPgogICAgPGRpdiBjbGFzcz0iZmllbGQiPgogICAgICA8bGFiZWw+RGkgY29zYSBzaSBkaXNjdXRlPzwvbGFiZWw+CiAgICAgIDxpbnB1dCB0eXBlPSJ0ZXh0IiBpZD0idG9waWNJbnB1dCIgcGxhY2Vob2xkZXI9IkVzOiBMYSBjYW5uYWJpcyBkb3ZyZWJiZSBlc3NlcmUgbGVnYWxpenphdGEgaW4gSXRhbGlhIiAvPgogICAgPC9kaXY+CiAgPC9kaXY+CgogIDxkaXYgY2xhc3M9InNldHVwLWNhcmQiPgogICAgPGgyPvCfkaUgUGFydGVjaXBhbnRpPC9oMj4KICAgIDxkaXYgY2xhc3M9InBhcnRpY2lwYW50cy1saXN0IiBpZD0icGFydGljaXBhbnRzTGlzdCI+PC9kaXY+CiAgICA8YnV0dG9uIGNsYXNzPSJidG4tYWRkIiBvbmNsaWNrPSJhZGRQYXJ0aWNpcGFudCgpIj4rIEFnZ2l1bmdpIHBhcnRlY2lwYW50ZTwvYnV0dG9uPgogIDwvZGl2PgoKICA8ZGl2IGNsYXNzPSJzZXR1cC1jYXJkIj4KICAgIDxoMj7wn46vIE9iaWV0dGl2byBkZWwgZGliYXR0aXRvPC9oMj4KICAgIDxkaXYgY2xhc3M9Im9iamVjdGl2ZS1ncmlkIiBpZD0ib2JqZWN0aXZlR3JpZCI+CiAgICAgIDxidXR0b24gY2xhc3M9Im9iai1idG4gc2VsIiBkYXRhLW9iaj0iZmFjdHMiIG9uY2xpY2s9InNlbGVjdE9iaih0aGlzKSI+CiAgICAgICAgPHNwYW4gY2xhc3M9Im9iai1pY29uIj7impbvuI88L3NwYW4+CiAgICAgICAgPHNwYW4gY2xhc3M9Im9iai1sYWJlbCI+Q2hpIGhhIHJhZ2lvbmU8L3NwYW4+CiAgICAgICAgPHNwYW4gY2xhc3M9Im9iai1kZXNjIj5BbmFsaXNpIGZhdHR1YWxlIOKAlCBjaGkgYXJnb21lbnRhIG1lZ2xpbyBzdWkgZmF0dGk8L3NwYW4+CiAgICAgIDwvYnV0dG9uPgogICAgICA8YnV0dG9uIGNsYXNzPSJvYmotYnRuIiBkYXRhLW9iaj0iY3JpdGljYWwiIG9uY2xpY2s9InNlbGVjdE9iaih0aGlzKSI+CiAgICAgICAgPHNwYW4gY2xhc3M9Im9iai1pY29uIj7wn6egPC9zcGFuPgogICAgICAgIDxzcGFuIGNsYXNzPSJvYmotbGFiZWwiPlBlbnNpZXJvIGNyaXRpY288L3NwYW4+CiAgICAgICAgPHNwYW4gY2xhc3M9Im9iai1kZXNjIj5WYWx1dGEgbGEgcXVhbGl0w6AgZGVsIHJhZ2lvbmFtZW50byBkaSBjaWFzY3Vubzwvc3Bhbj4KICAgICAgPC9idXR0b24+CiAgICAgIDxidXR0b24gY2xhc3M9Im9iai1idG4iIGRhdGEtb2JqPSJzeW50aGVzaXMiIG9uY2xpY2s9InNlbGVjdE9iaih0aGlzKSI+CiAgICAgICAgPHNwYW4gY2xhc3M9Im9iai1pY29uIj7wn6SdPC9zcGFuPgogICAgICAgIDxzcGFuIGNsYXNzPSJvYmotbGFiZWwiPlNpbnRlc2kgY29uZGl2aXNhPC9zcGFuPgogICAgICAgIDxzcGFuIGNsYXNzPSJvYmotZGVzYyI+VHJvdmEgaSBwdW50aSBkaSBhY2NvcmRvIHBvc3NpYmlsaTwvc3Bhbj4KICAgICAgPC9idXR0b24+CiAgICAgIDxidXR0b24gY2xhc3M9Im9iai1idG4iIGRhdGEtb2JqPSJkb2N1bWVudCIgb25jbGljaz0ic2VsZWN0T2JqKHRoaXMpIj4KICAgICAgICA8c3BhbiBjbGFzcz0ib2JqLWljb24iPvCfk4Q8L3NwYW4+CiAgICAgICAgPHNwYW4gY2xhc3M9Im9iai1sYWJlbCI+RG9jdW1lbnRhIHBvc2l6aW9uaTwvc3Bhbj4KICAgICAgICA8c3BhbiBjbGFzcz0ib2JqLWRlc2MiPk1hcHBhIGxlIHBvc2l6aW9uaSBkaSB0dXR0aSBpIHBhcnRlY2lwYW50aTwvc3Bhbj4KICAgICAgPC9idXR0b24+CiAgICA8L2Rpdj4KICA8L2Rpdj4KCiAgPGJ1dHRvbiBjbGFzcz0iYnRuLXN0YXJ0IiBpZD0ic3RhcnRCdG4iIG9uY2xpY2s9InN0YXJ0RGViYXRlKCkiPuKalO+4jyBJbml6aWEgaWwgZGliYXR0aXRvPC9idXR0b24+Cgo8L2Rpdj4KCjwhLS0g4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQIERFQkFURSDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAgLS0+CjxkaXYgaWQ9ImRlYmF0ZVNjcmVlbiI+CgogIDxkaXYgY2xhc3M9ImRlYmF0ZS1oZWFkZXIiPgogICAgPGRpdiBjbGFzcz0iZGViYXRlLXRvcGljIj4KICAgICAgPGRpdiBjbGFzcz0idG9waWMtbGFiZWwiPkFyZ29tZW50bzwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJ0b3BpYy10ZXh0IiBpZD0iZGViYXRlVG9waWMiPjwvZGl2PgogICAgPC9kaXY+CiAgICA8c3BhbiBjbGFzcz0idHVybi1jb3VudGVyIiBpZD0idHVybkNvdW50ZXIiPjAgaW50ZXJ2ZW50aTwvc3Bhbj4KICAgIDxidXR0b24gY2xhc3M9ImJ0bi1lbmQiIG9uY2xpY2s9ImVuZERlYmF0ZSgpIj5DaGl1ZGkgZSBnZW5lcmEgcmVwb3J0IOKGkjwvYnV0dG9uPgogIDwvZGl2PgoKICA8ZGl2IGNsYXNzPSJkZWJhdGUtbGF5b3V0Ij4KICAgIDxkaXY+CiAgICAgIDxkaXYgY2xhc3M9ImFpLXBhbmVsLXRpdGxlIj5QYXJ0ZWNpcGFudGkg4oCUIGNsaWNjYSBwZXIgcGFybGFyZTwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJzcGVha2Vycy1hcmVhIiBpZD0ic3BlYWtlcnNBcmVhIj48L2Rpdj4KICAgIDwvZGl2PgoKICAgIDxkaXYgY2xhc3M9ImFpLXBhbmVsIj4KICAgICAgPGRpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJhaS1wYW5lbC10aXRsZSI+QUkgaW4gdGVtcG8gcmVhbGU8L2Rpdj4KICAgICAgICA8ZGl2IGlkPSJhaUZlZWQiIHN0eWxlPSJkaXNwbGF5OmZsZXg7ZmxleC1kaXJlY3Rpb246Y29sdW1uO2dhcDo4cHg7bWF4LWhlaWdodDo0MDBweDtvdmVyZmxvdy15OmF1dG8iPjwvZGl2PgogICAgICA8L2Rpdj4KICAgICAgPGRpdj4KICAgICAgICA8ZGl2IGNsYXNzPSJhaS1wYW5lbC10aXRsZSIgc3R5bGU9Im1hcmdpbi10b3A6MTJweCI+U29saWRpdMOgIGFyZ29tZW50aTwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9InNjb3Jlcy1wYW5lbCIgaWQ9InNjb3Jlc1BhbmVsIj48L2Rpdj4KICAgICAgPC9kaXY+CiAgICAgIDxkaXY+CiAgICAgICAgPGRpdiBjbGFzcz0iYWktcGFuZWwtdGl0bGUiIHN0eWxlPSJtYXJnaW4tdG9wOjEycHgiPkZlZWQgaW50ZXJ2ZW50aTwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9ImZlZWQiIGlkPSJkZWJhdGVGZWVkIj48L2Rpdj4KICAgICAgPC9kaXY+CiAgICA8L2Rpdj4KICA8L2Rpdj4KCjwvZGl2PgoKPCEtLSDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAgUkVQT1JUIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkCAtLT4KPGRpdiBpZD0icmVwb3J0U2NyZWVuIj4KICA8ZGl2IHN0eWxlPSJkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDoxMnB4O21hcmdpbi1ib3R0b206MjBweCI+CiAgICA8aDIgc3R5bGU9ImZvbnQtc2l6ZToyMHB4O2ZvbnQtd2VpZ2h0OjYwMCI+UmVwb3J0IGZpbmFsZTwvaDI+CiAgICA8c3BhbiBzdHlsZT0iZm9udC1zaXplOjEzcHg7Y29sb3I6dmFyKC0tbXV0ZWQpIiBpZD0icmVwb3J0VG9waWMiPjwvc3Bhbj4KICAgIDxidXR0b24gb25jbGljaz0iZG93bmxvYWREZWJhdGVSZXBvcnQoKSIgc3R5bGU9Im1hcmdpbi1sZWZ0OmF1dG87cGFkZGluZzo4cHggMTZweDtib3JkZXI6MC41cHggc29saWQgdmFyKC0tYm9yZGVyMik7Ym9yZGVyLXJhZGl1czo4cHg7YmFja2dyb3VuZDp2YXIoLS1zdXJmYWNlKTtjb2xvcjp2YXIoLS10ZXh0KTtmb250LXNpemU6MTNweDtjdXJzb3I6cG9pbnRlciI+4qyHIFNjYXJpY2E8L2J1dHRvbj4KICA8L2Rpdj4KICA8ZGl2IGlkPSJyZXBvcnRDb250ZW50Ij48L2Rpdj4KICA8YnV0dG9uIG9uY2xpY2s9ImxvY2F0aW9uLmhyZWY9Jy9kZWJhdGUnIiBzdHlsZT0ibWFyZ2luLXRvcDoxNnB4O3BhZGRpbmc6MTBweCAyMHB4O2JvcmRlcjowLjVweCBzb2xpZCB2YXIoLS1wdXJwbGUpO2JvcmRlci1yYWRpdXM6OHB4O2JhY2tncm91bmQ6cmdiYSgxMjQsMTA2LDI0NywuMSk7Y29sb3I6dmFyKC0tcHVycGxlKTtmb250LXNpemU6MTNweDtjdXJzb3I6cG9pbnRlcjtmb250LWZhbWlseTp2YXIoLS1mb250KSI+4oapIE51b3ZvIGRpYmF0dGl0bzwvYnV0dG9uPgo8L2Rpdj4KCjwvZGl2PgoKPHNjcmlwdD4KY29uc3QgQ09MT1JTID0gWycjZTk0NTYwJywnIzdjNmFmNycsJyMyMmM1NWUnLCcjZjU5ZTBiJywnIzM4YmRmOCcsJyNmNDcyYjYnLCcjYTc4YmZhJywnIzM0ZDM5OSddOwpsZXQgcGFydGljaXBhbnRzID0gW107CmxldCBzZWxlY3RlZE9iaiA9ICdmYWN0cyc7CmxldCBkZWJhdGVTdGF0ZSA9IHsKICB0b3BpYzogJycsIG9iamVjdGl2ZTogJycsIGFwaUtleTogJycsCiAgdHVybnM6IDAsIHRyYW5zY3JpcHQ6IFtdLCBhbmFseXNlczogW10sCiAgc2NvcmVzOiB7fSwgcmVjb2duaXRpb246IG51bGwsIGFjdGl2ZVNwZWFrZXI6IG51bGwKfTsKCmNvbnN0IG9iakxhYmVscyA9IHsKICBmYWN0czogJ0NoaSBoYSByYWdpb25lIHN1aSBmYXR0aScsCiAgY3JpdGljYWw6ICdBbGxlbmFyZSBpbCBwZW5zaWVybyBjcml0aWNvJywKICBzeW50aGVzaXM6ICdUcm92YXJlIHNpbnRlc2kgY29uZGl2aXNhJywKICBkb2N1bWVudDogJ0RvY3VtZW50YXJlIGxlIHBvc2l6aW9uaScKfTsKCi8vIOKUgOKUgCBTZXR1cCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKCmZ1bmN0aW9uIGFkZFBhcnRpY2lwYW50KG5hbWUgPSAnJykgewogIGNvbnN0IGNvbG9yID0gQ09MT1JTW3BhcnRpY2lwYW50cy5sZW5ndGggJSBDT0xPUlMubGVuZ3RoXTsKICBjb25zdCBpZCA9ICdwJyArIERhdGUubm93KCk7CiAgcGFydGljaXBhbnRzLnB1c2goeyBpZCwgbmFtZSwgY29sb3IsIHNjb3JlOiA1MCB9KTsKICByZW5kZXJQYXJ0aWNpcGFudHNMaXN0KCk7Cn0KCmZ1bmN0aW9uIHJlbW92ZVBhcnRpY2lwYW50KGlkKSB7CiAgcGFydGljaXBhbnRzID0gcGFydGljaXBhbnRzLmZpbHRlcihwID0+IHAuaWQgIT09IGlkKTsKICByZW5kZXJQYXJ0aWNpcGFudHNMaXN0KCk7Cn0KCmZ1bmN0aW9uIHJlbmRlclBhcnRpY2lwYW50c0xpc3QoKSB7CiAgY29uc3QgbGlzdCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdwYXJ0aWNpcGFudHNMaXN0Jyk7CiAgbGlzdC5pbm5lckhUTUwgPSBwYXJ0aWNpcGFudHMubWFwKHAgPT4gYAogICAgPGRpdiBjbGFzcz0icGFydGljaXBhbnQtcm93Ij4KICAgICAgPGRpdiBjbGFzcz0iY29sb3ItZG90IiBzdHlsZT0iYmFja2dyb3VuZDoke3AuY29sb3J9Ij48L2Rpdj4KICAgICAgPGlucHV0IHR5cGU9InRleHQiIHBsYWNlaG9sZGVyPSJOb21lIHBhcnRlY2lwYW50ZSIgdmFsdWU9IiR7cC5uYW1lfSIKICAgICAgICBvbmlucHV0PSJ1cGRhdGVOYW1lKCcke3AuaWR9JywgdGhpcy52YWx1ZSkiIC8+CiAgICAgIDxidXR0b24gY2xhc3M9ImJ0bi1yZW1vdmUiIG9uY2xpY2s9InJlbW92ZVBhcnRpY2lwYW50KCcke3AuaWR9JykiPsOXPC9idXR0b24+CiAgICA8L2Rpdj4KICBgKS5qb2luKCcnKTsKfQoKZnVuY3Rpb24gdXBkYXRlTmFtZShpZCwgbmFtZSkgewogIGNvbnN0IHAgPSBwYXJ0aWNpcGFudHMuZmluZChwID0+IHAuaWQgPT09IGlkKTsKICBpZiAocCkgcC5uYW1lID0gbmFtZTsKfQoKZnVuY3Rpb24gc2VsZWN0T2JqKGJ0bikgewogIGRvY3VtZW50LnF1ZXJ5U2VsZWN0b3JBbGwoJy5vYmotYnRuJykuZm9yRWFjaChiID0+IGIuY2xhc3NMaXN0LnJlbW92ZSgnc2VsJykpOwogIGJ0bi5jbGFzc0xpc3QuYWRkKCdzZWwnKTsKICBzZWxlY3RlZE9iaiA9IGJ0bi5kYXRhc2V0Lm9iajsKfQoKZnVuY3Rpb24gc2hvd0Vycm9yKG1zZykgewogIGNvbnN0IGVsID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Vycm9yQm94Jyk7CiAgZWwudGV4dENvbnRlbnQgPSAn4pqgICcgKyBtc2c7CiAgZWwuY2xhc3NMaXN0LmFkZCgnc2hvdycpOwogIHNldFRpbWVvdXQoKCkgPT4gZWwuY2xhc3NMaXN0LnJlbW92ZSgnc2hvdycpLCA1MDAwKTsKfQoKZnVuY3Rpb24gc3RhcnREZWJhdGUoKSB7CiAgY29uc3Qga2V5ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2FwaUtleScpLnZhbHVlLnRyaW0oKTsKICBjb25zdCB0b3BpYyA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0b3BpY0lucHV0JykudmFsdWUudHJpbSgpOwoKICBpZiAoIWtleSkgcmV0dXJuIHNob3dFcnJvcignSW5zZXJpc2NpIGxhIGNoaWF2ZSBBUEkgQW50aHJvcGljJyk7CiAgaWYgKCF0b3BpYykgcmV0dXJuIHNob3dFcnJvcignSW5zZXJpc2NpIGxcJ2FyZ29tZW50byBkZWwgZGliYXR0aXRvJyk7CgogIC8vIFN5bmMgbmFtZXMKICBkb2N1bWVudC5xdWVyeVNlbGVjdG9yQWxsKCcucGFydGljaXBhbnQtcm93IGlucHV0JykuZm9yRWFjaCgoaW5wLCBpKSA9PiB7CiAgICBpZiAocGFydGljaXBhbnRzW2ldKSBwYXJ0aWNpcGFudHNbaV0ubmFtZSA9IGlucC52YWx1ZSB8fCAnUGFydGVjaXBhbnRlICcgKyAoaSArIDEpOwogIH0pOwoKICBjb25zdCB2YWxpZFAgPSBwYXJ0aWNpcGFudHMuZmlsdGVyKHAgPT4gcC5uYW1lLnRyaW0oKSk7CiAgaWYgKHZhbGlkUC5sZW5ndGggPCAyKSByZXR1cm4gc2hvd0Vycm9yKCdBZ2dpdW5naSBhbG1lbm8gMiBwYXJ0ZWNpcGFudGknKTsKCiAgZGViYXRlU3RhdGUgPSB7CiAgICB0b3BpYywgb2JqZWN0aXZlOiBvYmpMYWJlbHNbc2VsZWN0ZWRPYmpdLCBhcGlLZXk6IGtleSwKICAgIHR1cm5zOiAwLCB0cmFuc2NyaXB0OiBbXSwgYW5hbHlzZXM6IFtdLAogICAgc2NvcmVzOiB7fSwgcmVjb2duaXRpb246IG51bGwsIGFjdGl2ZVNwZWFrZXI6IG51bGwKICB9OwoKICB2YWxpZFAuZm9yRWFjaChwID0+IHsgZGViYXRlU3RhdGUuc2NvcmVzW3AuaWRdID0gNTA7IH0pOwoKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnc2V0dXBTY3JlZW4nKS5zdHlsZS5kaXNwbGF5ID0gJ25vbmUnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdkZWJhdGVTY3JlZW4nKS5zdHlsZS5kaXNwbGF5ID0gJ2Jsb2NrJzsKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGViYXRlVG9waWMnKS50ZXh0Q29udGVudCA9IHRvcGljOwoKICByZW5kZXJTcGVha2Vycyh2YWxpZFApOwogIHJlbmRlclNjb3Jlcyh2YWxpZFApOwp9CgovLyDilIDilIAgRGViYXRlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKZnVuY3Rpb24gcmVuZGVyU3BlYWtlcnMocGFydHMpIHsKICBjb25zdCBhcmVhID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3NwZWFrZXJzQXJlYScpOwogIGFyZWEuaW5uZXJIVE1MID0gcGFydHMubWFwKHAgPT4gYAogICAgPGRpdiBjbGFzcz0ic3BlYWtlci1idG4iIGlkPSJzcGtfJHtwLmlkfSIgc3R5bGU9ImJvcmRlci1jb2xvcjoke3AuY29sb3J9MjA7YmFja2dyb3VuZDoke3AuY29sb3J9MDgiCiAgICAgICAgIG9uY2xpY2s9InRvZ2dsZVNwZWFrZXIoJyR7cC5pZH0nKSI+CiAgICAgIDxkaXYgY2xhc3M9InJlYy1pbmRpY2F0b3IiIGlkPSJyZWNfJHtwLmlkfSI+PC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9InNwZWFrZXItbmFtZSIgc3R5bGU9ImNvbG9yOiR7cC5jb2xvcn0iPiR7cC5uYW1lfTwvZGl2PgogICAgICA8ZGl2IGNsYXNzPSJzcGVha2VyLXNjb3JlIiBzdHlsZT0iY29sb3I6JHtwLmNvbG9yfTk5Ij5Tb2xpZGl0w6A6IDxzcGFuIGlkPSJzY18ke3AuaWR9Ij41MDwvc3Bhbj4lPC9kaXY+CiAgICAgIDxkaXYgY2xhc3M9InNwZWFrZXItdHJhbnNjcmlwdCIgaWQ9InRyXyR7cC5pZH0iPkNsaWNjYSBwZXIgaW5pemlhcmUgYSBwYXJsYXJlLi4uPC9kaXY+CiAgICAgIDxidXR0b24gY2xhc3M9InNwZWFrZXItc3RvcCIgaWQ9InN0b3BfJHtwLmlkfSIgb25jbGljaz0iZXZlbnQuc3RvcFByb3BhZ2F0aW9uKCk7c3RvcFNwZWFrZXIoJyR7cC5pZH0nKSI+CiAgICAgICAg4pyTIEZpbml0byDigJQgYW5hbGl6emEgaW50ZXJ2ZW50bwogICAgICA8L2J1dHRvbj4KICAgIDwvZGl2PgogIGApLmpvaW4oJycpOwp9CgpmdW5jdGlvbiByZW5kZXJTY29yZXMocGFydHMpIHsKICBjb25zdCBwYW5lbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzY29yZXNQYW5lbCcpOwogIHBhbmVsLmlubmVySFRNTCA9IHBhcnRzLm1hcChwID0+IGAKICAgIDxkaXYgY2xhc3M9InNjb3JlLXJvdyI+CiAgICAgIDxzcGFuIGNsYXNzPSJzY29yZS1uYW1lIiBzdHlsZT0iY29sb3I6JHtwLmNvbG9yfSI+JHtwLm5hbWV9PC9zcGFuPgogICAgICA8ZGl2IGNsYXNzPSJzY29yZS1iYXItYmciPgogICAgICAgIDxkaXYgY2xhc3M9InNjb3JlLWJhci1maWxsIiBpZD0iYmFyXyR7cC5pZH0iIHN0eWxlPSJ3aWR0aDo1MCU7YmFja2dyb3VuZDoke3AuY29sb3J9Ij48L2Rpdj4KICAgICAgPC9kaXY+CiAgICAgIDxzcGFuIGNsYXNzPSJzY29yZS12YWwiIGlkPSJiYXJ2YWxfJHtwLmlkfSI+NTA8L3NwYW4+CiAgICA8L2Rpdj4KICBgKS5qb2luKCcnKTsKfQoKbGV0IGFjdGl2ZVJlY29nbml0aW9ucyA9IHt9OwoKZnVuY3Rpb24gdG9nZ2xlU3BlYWtlcihpZCkgewogIGlmIChkZWJhdGVTdGF0ZS5hY3RpdmVTcGVha2VyID09PSBpZCkgcmV0dXJuOwogIGlmIChkZWJhdGVTdGF0ZS5hY3RpdmVTcGVha2VyKSBzdG9wU3BlYWtlcihkZWJhdGVTdGF0ZS5hY3RpdmVTcGVha2VyLCB0cnVlKTsKICBzdGFydFNwZWFrZXIoaWQpOwp9CgpmdW5jdGlvbiBzdGFydFNwZWFrZXIoaWQpIHsKICBjb25zdCBTcGVlY2hSZWNvZ25pdGlvbiA9IHdpbmRvdy5TcGVlY2hSZWNvZ25pdGlvbiB8fCB3aW5kb3cud2Via2l0U3BlZWNoUmVjb2duaXRpb247CiAgaWYgKCFTcGVlY2hSZWNvZ25pdGlvbikgewogICAgc2hvd0Vycm9yKCdSaWNvbm9zY2ltZW50byB2b2NhbGUgbm9uIHN1cHBvcnRhdG8uIFVzYSBDaHJvbWUgbyBFZGdlLicpOwogICAgcmV0dXJuOwogIH0KCiAgZGViYXRlU3RhdGUuYWN0aXZlU3BlYWtlciA9IGlkOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdyZWNfJyArIGlkKS5jbGFzc0xpc3QuYWRkKCdvbicpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzdG9wXycgKyBpZCkuY2xhc3NMaXN0LmFkZCgnc2hvdycpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0cl8nICsgaWQpLnRleHRDb250ZW50ID0gJ/CfjpkgSW4gYXNjb2x0by4uLic7CgogIGNvbnN0IHJlYyA9IG5ldyBTcGVlY2hSZWNvZ25pdGlvbigpOwogIHJlYy5sYW5nID0gJ2l0LUlUJzsKICByZWMuY29udGludW91cyA9IHRydWU7CiAgcmVjLmludGVyaW1SZXN1bHRzID0gdHJ1ZTsKCiAgbGV0IGJ1ZmZlciA9ICcnOwogIHJlYy5vbnJlc3VsdCA9IChlKSA9PiB7CiAgICBsZXQgaW50ZXJpbSA9ICcnLCBmaW5hbCA9ICcnOwogICAgZm9yIChsZXQgaSA9IGUucmVzdWx0SW5kZXg7IGkgPCBlLnJlc3VsdHMubGVuZ3RoOyBpKyspIHsKICAgICAgaWYgKGUucmVzdWx0c1tpXS5pc0ZpbmFsKSBmaW5hbCArPSBlLnJlc3VsdHNbaV1bMF0udHJhbnNjcmlwdCArICcgJzsKICAgICAgZWxzZSBpbnRlcmltICs9IGUucmVzdWx0c1tpXVswXS50cmFuc2NyaXB0OwogICAgfQogICAgaWYgKGZpbmFsKSBidWZmZXIgKz0gZmluYWw7CiAgICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgndHJfJyArIGlkKS50ZXh0Q29udGVudCA9IGJ1ZmZlciArIChpbnRlcmltID8gaW50ZXJpbSA6ICcnKTsKICB9OwoKICByZWMub25lcnJvciA9ICgpID0+IHt9OwogIHJlYy5vbmVuZCA9ICgpID0+IHsgaWYgKGRlYmF0ZVN0YXRlLmFjdGl2ZVNwZWFrZXIgPT09IGlkKSByZWMuc3RhcnQoKTsgfTsKICByZWMuc3RhcnQoKTsKCiAgYWN0aXZlUmVjb2duaXRpb25zW2lkXSA9IHsgcmVjLCBnZXRCdWZmZXI6ICgpID0+IGJ1ZmZlciB9Owp9Cgphc3luYyBmdW5jdGlvbiBzdG9wU3BlYWtlcihpZCwgc2lsZW50ID0gZmFsc2UpIHsKICBjb25zdCByZWNEYXRhID0gYWN0aXZlUmVjb2duaXRpb25zW2lkXTsKICBpZiAocmVjRGF0YSkgewogICAgcmVjRGF0YS5yZWMuc3RvcCgpOwogICAgZGVsZXRlIGFjdGl2ZVJlY29nbml0aW9uc1tpZF07CiAgfQoKICBjb25zdCB0ZXh0ID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RyXycgKyBpZCk/LnRleHRDb250ZW50IHx8ICcnOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdyZWNfJyArIGlkKS5jbGFzc0xpc3QucmVtb3ZlKCdvbicpOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzdG9wXycgKyBpZCkuY2xhc3NMaXN0LnJlbW92ZSgnc2hvdycpOwogIGRlYmF0ZVN0YXRlLmFjdGl2ZVNwZWFrZXIgPSBudWxsOwoKICBpZiAoc2lsZW50IHx8ICF0ZXh0IHx8IHRleHQubGVuZ3RoIDwgMTAgfHwgdGV4dCA9PT0gJ/CfjpkgSW4gYXNjb2x0by4uLicpIHJldHVybjsKCiAgLy8gRmluZCBwYXJ0aWNpcGFudAogIGNvbnN0IHAgPSBwYXJ0aWNpcGFudHMuZmluZChwID0+IHAuaWQgPT09IGlkKTsKICBpZiAoIXApIHJldHVybjsKCiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RyXycgKyBpZCkudGV4dENvbnRlbnQgPSAn4o+zIEFJIHN0YSBhbmFsaXp6YW5kby4uLic7CgogIHRyeSB7CiAgICBjb25zdCBoaXN0b3J5ID0gZGViYXRlU3RhdGUudHJhbnNjcmlwdAogICAgICAuc2xpY2UoLTUpCiAgICAgIC5tYXAodCA9PiBgJHt0LnNwZWFrZXJ9OiAke3QudGV4dH1gKQogICAgICAuam9pbignXG4nKTsKCiAgICBjb25zdCByZXNwID0gYXdhaXQgZmV0Y2goJy9hcGkvZGViYXRlL3R1cm4nLCB7CiAgICAgIG1ldGhvZDogJ1BPU1QnLAogICAgICBoZWFkZXJzOiB7ICdDb250ZW50LVR5cGUnOiAnYXBwbGljYXRpb24vanNvbicgfSwKICAgICAgYm9keTogSlNPTi5zdHJpbmdpZnkoewogICAgICAgIGFudGhyb3BpY19rZXk6IGRlYmF0ZVN0YXRlLmFwaUtleSwKICAgICAgICB0ZXh0LCBzcGVha2VyOiBwLm5hbWUsCiAgICAgICAgdG9waWM6IGRlYmF0ZVN0YXRlLnRvcGljLAogICAgICAgIG9iamVjdGl2ZTogZGViYXRlU3RhdGUub2JqZWN0aXZlLAogICAgICAgIGhpc3RvcnkKICAgICAgfSkKICAgIH0pOwoKICAgIGNvbnN0IGRhdGEgPSBhd2FpdCByZXNwLmpzb24oKTsKICAgIGlmIChkYXRhLmVycm9yKSB0aHJvdyBuZXcgRXJyb3IoZGF0YS5lcnJvcik7CgogICAgLy8gU2F2ZQogICAgZGViYXRlU3RhdGUudHJhbnNjcmlwdC5wdXNoKHsgc3BlYWtlcjogcC5uYW1lLCB0ZXh0LCBjb2xvcjogcC5jb2xvciB9KTsKICAgIGRlYmF0ZVN0YXRlLmFuYWx5c2VzLnB1c2goZGF0YSk7CiAgICBkZWJhdGVTdGF0ZS50dXJucysrOwoKICAgIC8vIFVwZGF0ZSBzY29yZQogICAgY29uc3QgbmV3U2NvcmUgPSBNYXRoLnJvdW5kKChkZWJhdGVTdGF0ZS5zY29yZXNbaWRdICogMC42KSArIChkYXRhLmFyZ3VtZW50X3N0cmVuZ3RoICogMC40KSk7CiAgICBkZWJhdGVTdGF0ZS5zY29yZXNbaWRdID0gTWF0aC5tYXgoMCwgTWF0aC5taW4oMTAwLCBuZXdTY29yZSkpOwogICAgdXBkYXRlU2NvcmUoaWQsIGRlYmF0ZVN0YXRlLnNjb3Jlc1tpZF0sIHAuY29sb3IpOwoKICAgIC8vIFNob3cgaW4gQUkgZmVlZAogICAgYWRkQWlGZWVkSXRlbShkYXRhLCBwKTsKCiAgICAvLyBBZGQgdG8gZGViYXRlIGZlZWQKICAgIGFkZEZlZWRJdGVtKHAsIHRleHQsIGRhdGEpOwoKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCd0dXJuQ291bnRlcicpLnRleHRDb250ZW50ID0gZGViYXRlU3RhdGUudHVybnMgKyAnIGludGVydmVudGknOwogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RyXycgKyBpZCkudGV4dENvbnRlbnQgPSAnQ2xpY2NhIHBlciBwYXJsYXJlIGRpIG51b3ZvLi4uJzsKCiAgfSBjYXRjaCAoZSkgewogICAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3RyXycgKyBpZCkudGV4dENvbnRlbnQgPSAn4pqgIEVycm9yZTogJyArIGUubWVzc2FnZTsKICB9Cn0KCmZ1bmN0aW9uIHVwZGF0ZVNjb3JlKGlkLCB2YWwsIGNvbG9yKSB7CiAgY29uc3QgYmFyID0gZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2Jhcl8nICsgaWQpOwogIGNvbnN0IGJhcnZhbCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdiYXJ2YWxfJyArIGlkKTsKICBjb25zdCBzYyA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdzY18nICsgaWQpOwogIGlmIChiYXIpIGJhci5zdHlsZS53aWR0aCA9IHZhbCArICclJzsKICBpZiAoYmFydmFsKSBiYXJ2YWwudGV4dENvbnRlbnQgPSB2YWw7CiAgaWYgKHNjKSBzYy50ZXh0Q29udGVudCA9IHZhbDsKfQoKZnVuY3Rpb24gYWRkQWlGZWVkSXRlbShkYXRhLCBwKSB7CiAgY29uc3QgZmVlZCA9IGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdhaUZlZWQnKTsKICBjb25zdCBmbGFnQ2xhc3MgPSBkYXRhLmZsYWcgfHwgJ25vbmUnOwogIGNvbnN0IGNsYWltcyA9IChkYXRhLmNsYWltcyB8fCBbXSkuZmlsdGVyKGMgPT4gYy52ZXJkaWN0X2tleSAhPT0gJ29waW5pb24nKS5zbGljZSgwLCAyKTsKCiAgY29uc3QgZGl2ID0gZG9jdW1lbnQuY3JlYXRlRWxlbWVudCgnZGl2Jyk7CiAgZGl2LmNsYXNzTmFtZSA9IGBhaS1mbGFnICR7ZmxhZ0NsYXNzfWA7CiAgZGl2LmlubmVySFRNTCA9IGAKICAgIDxkaXYgY2xhc3M9ImZsYWctc3BlYWtlciIgc3R5bGU9ImNvbG9yOiR7cC5jb2xvcn0iPiR7cC5uYW1lfSDigJQgJHtkYXRhLmZsYWdfbGFiZWwgfHwgJ2FuYWxpenphdG8nfTwvZGl2PgogICAgPGRpdiBjbGFzcz0iZmxhZy10ZXh0Ij4ke2RhdGEuYXJndW1lbnRfbm90ZSB8fCAnJ308L2Rpdj4KICAgICR7Y2xhaW1zLm1hcChjID0+IGA8ZGl2IHN0eWxlPSJtYXJnaW4tdG9wOjRweDtmb250LXNpemU6MTFweDtjb2xvcjp2YXIoLS1tdXRlZCkiPgogICAgICAke2MudmVyZGljdF9rZXkgPT09ICdmYWxzZScgPyAn4p2MJyA6IGMudmVyZGljdF9rZXkgPT09ICd0cnVlJyA/ICfinIUnIDogJ/Cfn6EnfSAke2MudGV4dC5zdWJzdHJpbmcoMCw4MCl9CiAgICA8L2Rpdj5gKS5qb2luKCcnKX0KICAgICR7ZGF0YS5yaGV0b3JpY190ZWNobmlxdWVzPy5sZW5ndGggPyBgPGRpdiBzdHlsZT0ibWFyZ2luLXRvcDo0cHg7Zm9udC1zaXplOjExcHg7Y29sb3I6dmFyKC0taW5mbykiPuKaoO+4jyAke2RhdGEucmhldG9yaWNfdGVjaG5pcXVlcy5qb2luKCcsICcpfTwvZGl2PmAgOiAnJ30KICAgICR7ZGF0YS5tb2RlcmF0b3JfcXVlc3Rpb24gPyBgPGRpdiBjbGFzcz0iZmxhZy1xdWVzdGlvbiI+8J+SrCAke2RhdGEubW9kZXJhdG9yX3F1ZXN0aW9ufTwvZGl2PmAgOiAnJ30KICBgOwogIGZlZWQuaW5zZXJ0QmVmb3JlKGRpdiwgZmVlZC5maXJzdENoaWxkKTsKfQoKZnVuY3Rpb24gYWRkRmVlZEl0ZW0ocCwgdGV4dCwgZGF0YSkgewogIGNvbnN0IGZlZWQgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgnZGViYXRlRmVlZCcpOwogIGNvbnN0IGRpdiA9IGRvY3VtZW50LmNyZWF0ZUVsZW1lbnQoJ2RpdicpOwogIGRpdi5jbGFzc05hbWUgPSAnZmVlZC1pdGVtJzsKICBkaXYuc3R5bGUuYm9yZGVyTGVmdENvbG9yID0gcC5jb2xvcjsKICBkaXYuc3R5bGUuYmFja2dyb3VuZCA9IHAuY29sb3IgKyAnMDgnOwogIGRpdi5pbm5lckhUTUwgPSBgCiAgICA8ZGl2IGNsYXNzPSJmZWVkLWl0ZW0tc3BlYWtlciIgc3R5bGU9ImNvbG9yOiR7cC5jb2xvcn0iPiR7cC5uYW1lfTwvZGl2PgogICAgPGRpdiBjbGFzcz0iZmVlZC1pdGVtLXRleHQiPiR7dGV4dC5zdWJzdHJpbmcoMCwgMTIwKX0ke3RleHQubGVuZ3RoID4gMTIwID8gJy4uLicgOiAnJ308L2Rpdj4KICAgIDxkaXYgY2xhc3M9ImZlZWQtaXRlbS1tZXRhIj5Tb2xpZGl0w6A6ICR7ZGF0YS5hcmd1bWVudF9zdHJlbmd0aH0lPC9kaXY+CiAgYDsKICBmZWVkLmluc2VydEJlZm9yZShkaXYsIGZlZWQuZmlyc3RDaGlsZCk7Cn0KCi8vIOKUgOKUgCBFbmQgJiBSZXBvcnQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACgphc3luYyBmdW5jdGlvbiBlbmREZWJhdGUoKSB7CiAgaWYgKGRlYmF0ZVN0YXRlLmFjdGl2ZVNwZWFrZXIpIHN0b3BTcGVha2VyKGRlYmF0ZVN0YXRlLmFjdGl2ZVNwZWFrZXIsIHRydWUpOwogIGlmIChkZWJhdGVTdGF0ZS50dXJucyA8IDIpIHsKICAgIHNob3dFcnJvcignU2VydmUgYWxtZW5vIDIgaW50ZXJ2ZW50aSBwZXIgZ2VuZXJhcmUgaWwgcmVwb3J0LicpOwogICAgcmV0dXJuOwogIH0KCiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ2RlYmF0ZVNjcmVlbicpLnN0eWxlLmRpc3BsYXkgPSAnbm9uZSc7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3JlcG9ydFNjcmVlbicpLnN0eWxlLmRpc3BsYXkgPSAnYmxvY2snOwogIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdyZXBvcnRUb3BpYycpLnRleHRDb250ZW50ID0gJ+KAlCAnICsgZGViYXRlU3RhdGUudG9waWM7CiAgZG9jdW1lbnQuZ2V0RWxlbWVudEJ5SWQoJ3JlcG9ydENvbnRlbnQnKS5pbm5lckhUTUwgPSAnPGRpdiBzdHlsZT0idGV4dC1hbGlnbjpjZW50ZXI7cGFkZGluZzo0MHB4O2NvbG9yOnZhcigtLW11dGVkKSI+PGRpdiBjbGFzcz0ic3Bpbm5lciI+PC9kaXY+PHAgc3R5bGU9Im1hcmdpbi10b3A6MTJweCI+QUkgc3RhIGdlbmVyYW5kbyBpbCByZXBvcnQgZmluYWxlLi4uPC9wPjwvZGl2Pic7CgogIHRyeSB7CiAgICBjb25zdCByZXNwID0gYXdhaXQgZmV0Y2goJy9hcGkvZGViYXRlL2ZpbmFsJywgewogICAgICBtZXRob2Q6ICdQT1NUJywKICAgICAgaGVhZGVyczogeyAnQ29udGVudC1UeXBlJzogJ2FwcGxpY2F0aW9uL2pzb24nIH0sCiAgICAgIGJvZHk6IEpTT04uc3RyaW5naWZ5KHsKICAgICAgICBhbnRocm9waWNfa2V5OiBkZWJhdGVTdGF0ZS5hcGlLZXksCiAgICAgICAgdG9waWM6IGRlYmF0ZVN0YXRlLnRvcGljLAogICAgICAgIG9iamVjdGl2ZTogZGViYXRlU3RhdGUub2JqZWN0aXZlLAogICAgICAgIHBhcnRpY2lwYW50czogcGFydGljaXBhbnRzLmZpbHRlcihwID0+IHAubmFtZSkubWFwKHAgPT4gcC5uYW1lKSwKICAgICAgICB0cmFuc2NyaXB0OiBkZWJhdGVTdGF0ZS50cmFuc2NyaXB0Lm1hcCh0ID0+IGAke3Quc3BlYWtlcn06ICR7dC50ZXh0fWApLmpvaW4oJ1xuXG4nKSwKICAgICAgICBhbmFseXNlczogZGViYXRlU3RhdGUuYW5hbHlzZXMKICAgICAgfSkKICAgIH0pOwoKICAgIGNvbnN0IGRhdGEgPSBhd2FpdCByZXNwLmpzb24oKTsKICAgIGlmIChkYXRhLmVycm9yKSB0aHJvdyBuZXcgRXJyb3IoZGF0YS5lcnJvcik7CiAgICByZW5kZXJSZXBvcnQoZGF0YSk7CgogIH0gY2F0Y2ggKGUpIHsKICAgIGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdyZXBvcnRDb250ZW50JykuaW5uZXJIVE1MID0gYDxkaXYgc3R5bGU9ImNvbG9yOnZhcigtLWFjY2VudCkiPuKaoCBFcnJvcmU6ICR7ZS5tZXNzYWdlfTwvZGl2PmA7CiAgfQp9CgpmdW5jdGlvbiByZW5kZXJSZXBvcnQoZGF0YSkgewogIGNvbnN0IHBNYXAgPSB7fTsKICBwYXJ0aWNpcGFudHMuZm9yRWFjaChwID0+IHsgcE1hcFtwLm5hbWVdID0gcC5jb2xvcjsgfSk7CgogIGxldCBodG1sID0gJyc7CgogIC8vIFdpbm5lcgogIGlmIChkYXRhLndpbm5lcl9mYWN0cykgewogICAgaHRtbCArPSBgPGRpdiBjbGFzcz0icmVwb3J0LXNlY3Rpb24iPjxoMz7impbvuI8gQ2hpIGF2ZXZhIHJhZ2lvbmUgc3VpIGZhdHRpPC9oMz48cCBzdHlsZT0iZm9udC1zaXplOjE0cHg7Y29sb3I6dmFyKC0tdGV4dCk7bGluZS1oZWlnaHQ6MS42Ij4ke2RhdGEud2lubmVyX2ZhY3RzfTwvcD48L2Rpdj5gOwogIH0KCiAgLy8gUG9zaXRpb25zCiAgaWYgKGRhdGEucG9zaXRpb25fc3VtbWFyeT8ubGVuZ3RoKSB7CiAgICBodG1sICs9IGA8ZGl2IGNsYXNzPSJyZXBvcnQtc2VjdGlvbiI+PGgzPvCfk4QgUG9zaXppb25pIGRlaSBwYXJ0ZWNpcGFudGk8L2gzPmA7CiAgICBkYXRhLnBvc2l0aW9uX3N1bW1hcnkuZm9yRWFjaChwb3MgPT4gewogICAgICBjb25zdCBjb2xvciA9IHBNYXBbcG9zLnNwZWFrZXJdIHx8ICcjN2M2YWY3JzsKICAgICAgaHRtbCArPSBgPGRpdiBjbGFzcz0icG9zaXRpb24tY2FyZCIgc3R5bGU9ImJvcmRlci1sZWZ0LWNvbG9yOiR7Y29sb3J9Ij4KICAgICAgICA8ZGl2IGNsYXNzPSJwb3Mtc3BlYWtlciIgc3R5bGU9ImNvbG9yOiR7Y29sb3J9Ij4ke3Bvcy5zcGVha2VyfTwvZGl2PgogICAgICAgIDxkaXYgY2xhc3M9InBvcy1wb3NpdGlvbiI+JHtwb3MucG9zaXRpb259PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0icG9zLXN0cm9uZyI+4pyFIFB1bnRvIGZvcnRlOiAke3Bvcy5zdHJvbmdlc3RfcG9pbnR9PC9kaXY+CiAgICAgICAgPGRpdiBjbGFzcz0icG9zLXdlYWsiPuKaoO+4jyBQdW50byBkZWJvbGU6ICR7cG9zLndlYWtlc3RfcG9pbnR9PC9kaXY+CiAgICAgIDwvZGl2PmA7CiAgICB9KTsKICAgIGh0bWwgKz0gYDwvZGl2PmA7CiAgfQoKICAvLyBTaGFyZWQgZ3JvdW5kCiAgaWYgKGRhdGEuc2hhcmVkX2dyb3VuZCkgewogICAgaHRtbCArPSBgPGRpdiBjbGFzcz0icmVwb3J0LXNlY3Rpb24iPjxoMz7wn6SdIFRlcnJlbm8gY29tdW5lPC9oMz48cCBzdHlsZT0iZm9udC1zaXplOjEzcHg7Y29sb3I6dmFyKC0tbXV0ZWQpO2xpbmUtaGVpZ2h0OjEuNiI+JHtkYXRhLnNoYXJlZF9ncm91bmR9PC9wPjwvZGl2PmA7CiAgfQoKICAvLyBDcml0aWNhbCB0aGlua2luZwogIGlmIChkYXRhLmNyaXRpY2FsX3RoaW5raW5nX25vdGVzPy5sZW5ndGgpIHsKICAgIGh0bWwgKz0gYDxkaXYgY2xhc3M9InJlcG9ydC1zZWN0aW9uIj48aDM+8J+noCBRdWFsaXTDoCBkZWwgcGVuc2llcm8gY3JpdGljbzwvaDM+YDsKICAgIGRhdGEuY3JpdGljYWxfdGhpbmtpbmdfbm90ZXMuZm9yRWFjaChuID0+IHsKICAgICAgY29uc3QgY29sb3IgPSBwTWFwW24uc3BlYWtlcl0gfHwgJyM3YzZhZjcnOwogICAgICBodG1sICs9IGA8ZGl2IHN0eWxlPSJwYWRkaW5nOjhweCAxMnB4O2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZTIpO2JvcmRlci1yYWRpdXM6OHB4O21hcmdpbi1ib3R0b206NnB4O2JvcmRlci1sZWZ0OjNweCBzb2xpZCAke2NvbG9yfSI+PHN0cm9uZyBzdHlsZT0iY29sb3I6JHtjb2xvcn0iPiR7bi5zcGVha2VyfTo8L3N0cm9uZz4gPHNwYW4gc3R5bGU9ImZvbnQtc2l6ZToxM3B4O2NvbG9yOnZhcigtLW11dGVkKSI+JHtuLm5vdGV9PC9zcGFuPjwvZGl2PmA7CiAgICB9KTsKICAgIGh0bWwgKz0gYDwvZGl2PmA7CiAgfQoKICAvLyBLZXkgY2xhaW1zCiAgaWYgKGRhdGEua2V5X2NsYWltc192ZXJpZmllZD8ubGVuZ3RoKSB7CiAgICBodG1sICs9IGA8ZGl2IGNsYXNzPSJyZXBvcnQtc2VjdGlvbiI+PGgzPvCflI0gQ2xhaW0gY2hpYXZlIHZlcmlmaWNhdGk8L2gzPmA7CiAgICBkYXRhLmtleV9jbGFpbXNfdmVyaWZpZWQuZm9yRWFjaChjID0+IHsKICAgICAgY29uc3QgY29sb3IgPSBwTWFwW2Muc3BlYWtlcl0gfHwgJyM3YzZhZjcnOwogICAgICBjb25zdCBpY29uID0gYy52ZXJkaWN0Py50b0xvd2VyQ2FzZSgpLmluY2x1ZGVzKCdmYWxzbycpID8gJ+KdjCcgOiBjLnZlcmRpY3Q/LnRvTG93ZXJDYXNlKCkuaW5jbHVkZXMoJ3Zlcm8nKSA/ICfinIUnIDogJ/Cfn6EnOwogICAgICBodG1sICs9IGA8ZGl2IHN0eWxlPSJwYWRkaW5nOjhweCAxMnB4O2JhY2tncm91bmQ6dmFyKC0tc3VyZmFjZTIpO2JvcmRlci1yYWRpdXM6OHB4O21hcmdpbi1ib3R0b206NnB4Ij48c3BhbiBzdHlsZT0iZm9udC1zaXplOjExcHg7Y29sb3I6JHtjb2xvcn0iPiR7Yy5zcGVha2VyfTwvc3Bhbj4g4oCUICR7aWNvbn0gPHNwYW4gc3R5bGU9ImZvbnQtc2l6ZToxM3B4O2NvbG9yOnZhcigtLW11dGVkKSI+JHtjLmNsYWltfTwvc3Bhbj4gPHNwYW4gc3R5bGU9ImZvbnQtc2l6ZToxMXB4O2NvbG9yOnZhcigtLWhpbnQpIj4oJHtjLnZlcmRpY3R9KTwvc3Bhbj48L2Rpdj5gOwogICAgfSk7CiAgICBodG1sICs9IGA8L2Rpdj5gOwogIH0KCiAgLy8gT3ZlcmFsbAogIGlmIChkYXRhLm92ZXJhbGxfcXVhbGl0eSkgewogICAgaHRtbCArPSBgPGRpdiBjbGFzcz0icmVwb3J0LXNlY3Rpb24iPjxoMz7wn5OKIFZhbHV0YXppb25lIGNvbXBsZXNzaXZhPC9oMz48cCBzdHlsZT0iZm9udC1zaXplOjEzcHg7Y29sb3I6dmFyKC0tbXV0ZWQpO2xpbmUtaGVpZ2h0OjEuNiI+JHtkYXRhLm92ZXJhbGxfcXVhbGl0eX08L3A+PC9kaXY+YDsKICB9CgogIC8vIE5leHQgcXVlc3Rpb25zCiAgaWYgKGRhdGEubmV4dF9xdWVzdGlvbnM/Lmxlbmd0aCkgewogICAgaHRtbCArPSBgPGRpdiBjbGFzcz0icmVwb3J0LXNlY3Rpb24iPjxoMz7wn5KtIERvbWFuZGUgYXBlcnRlIHJpbWFzdGU8L2gzPmA7CiAgICBkYXRhLm5leHRfcXVlc3Rpb25zLmZvckVhY2gocSA9PiB7CiAgICAgIGh0bWwgKz0gYDxkaXYgY2xhc3M9Im5leHQtcSI+JHtxfTwvZGl2PmA7CiAgICB9KTsKICAgIGh0bWwgKz0gYDwvZGl2PmA7CiAgfQoKICBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVwb3J0Q29udGVudCcpLmlubmVySFRNTCA9IGh0bWw7Cn0KCmZ1bmN0aW9uIGRvd25sb2FkRGViYXRlUmVwb3J0KCkgewogIGNvbnN0IGNvbnRlbnQgPSBkb2N1bWVudC5nZXRFbGVtZW50QnlJZCgncmVwb3J0Q29udGVudCcpLmlubmVySFRNTDsKICBjb25zdCB0b3BpYyA9IGRlYmF0ZVN0YXRlLnRvcGljOwogIGNvbnN0IGh0bWwgPSBgPCFET0NUWVBFIGh0bWw+PGh0bWw+PGhlYWQ+PG1ldGEgY2hhcnNldD0iVVRGLTgiPjx0aXRsZT5SZXBvcnQgRGliYXR0aXRvIOKAlCAke3RvcGljfTwvdGl0bGU+CiAgPHN0eWxlPmJvZHl7Zm9udC1mYW1pbHk6c2Fucy1zZXJpZjtwYWRkaW5nOjMycHg7bWF4LXdpZHRoOjgwMHB4O21hcmdpbjowIGF1dG87Y29sb3I6IzExMX1oMXtjb2xvcjojN2M2YWY3O21hcmdpbi1ib3R0b206OHB4fWgze21hcmdpbjoyMHB4IDAgMTBweDtjb2xvcjojMzMzfS5yZXBvcnQtc2VjdGlvbnttYXJnaW46MTZweCAwO3BhZGRpbmc6MTZweDtib3JkZXI6MXB4IHNvbGlkICNkZGQ7Ym9yZGVyLXJhZGl1czo4cHh9LnBvc2l0aW9uLWNhcmR7cGFkZGluZzoxMHB4IDE0cHg7Ym9yZGVyLWxlZnQ6NHB4IHNvbGlkICM3YzZhZjc7bWFyZ2luLWJvdHRvbTo4cHg7YmFja2dyb3VuZDojZjlmOWY5fS5uZXh0LXF7cGFkZGluZzo4cHggMTJweDtiYWNrZ3JvdW5kOiNmMGVlZmY7Ym9yZGVyLXJhZGl1czo2cHg7bWFyZ2luLWJvdHRvbTo2cHg7Y29sb3I6IzdjNmFmN308L3N0eWxlPgogIDwvaGVhZD48Ym9keT48aDE+UmVwb3J0IERpYmF0dGl0bzwvaDE+PHAgc3R5bGU9ImNvbG9yOiM4ODgiPiR7dG9waWN9IOKAlCAke25ldyBEYXRlKCkudG9Mb2NhbGVTdHJpbmcoJ2l0LUlUJyl9PC9wPiR7Y29udGVudH08L2JvZHk+PC9odG1sPmA7CiAgY29uc3QgYmxvYiA9IG5ldyBCbG9iKFtodG1sXSwgeyB0eXBlOiAndGV4dC9odG1sJyB9KTsKICBjb25zdCBhID0gZG9jdW1lbnQuY3JlYXRlRWxlbWVudCgnYScpOwogIGEuaHJlZiA9IFVSTC5jcmVhdGVPYmplY3RVUkwoYmxvYik7CiAgYS5kb3dubG9hZCA9ICdkaWJhdHRpdG8tJyArIG5ldyBEYXRlKCkudG9JU09TdHJpbmcoKS5zbGljZSgwLCAxMCkgKyAnLmh0bWwnOwogIGEuY2xpY2soKTsKfQoKLy8g4pSA4pSAIEluaXQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmFkZFBhcnRpY2lwYW50KCcnKTsKYWRkUGFydGljaXBhbnQoJycpOwo8L3NjcmlwdD4KPC9ib2R5Pgo8L2h0bWw+Cg==").decode('utf-8')

@app.route("/debate")
def debate_page():
    from flask import Response
    return Response(DEBATE_HTML, mimetype="text/html")
