import os
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

from medialens.anthropic_client import call_anthropic
from medialens.prompt_engine import build_analysis_prompt, build_synthesis_prompt
from medialens.schemas import INPUT_TYPES, ANALYSIS_TYPES


def clean_model_markup(text):
    if not text:
        return ""
    return (
        text
        .replace("<h1>", "# ").replace("</h1>", "\n")
        .replace("<h2>", "## ").replace("</h2>", "\n")
        .replace("<h3>", "### ").replace("</h3>", "\n")
        .replace("<hr>", "\n---\n").replace("<hr/>", "\n---\n").replace("<hr />", "\n---\n")
        .replace("<p>", "").replace("</p>", "\n")
        .replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    )

def call_clean_debug(prompt, api_key, label=""):
    raw = call_anthropic(prompt, api_key)
    cleaned = clean_model_markup(raw)

    print("\\n--- ML DEBUG", label, "---")
    print("RAW START:", repr(str(raw)[:300]))
    print("CLEAN START:", repr(str(cleaned)[:300]))
    print("RAW HAS HTML:", any(tag in str(raw).lower() for tag in ["<h1", "<h2", "<hr", "<p", "<br"]))
    print("CLEAN HAS HTML:", any(tag in str(cleaned).lower() for tag in ["<h1", "<h2", "<hr", "<p", "<br"]))
    print("--- END DEBUG ---\\n")

    return cleaned

app = Flask(__name__)
CORS(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config")
def config():
    return jsonify({
        "input_types": INPUT_TYPES,
        "analysis_types": ANALYSIS_TYPES
    })


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.json or {}

    api_key = data.get("anthropic_key") or ANTHROPIC_API_KEY
    if not api_key:
        return jsonify({"error": "Chiave API Anthropic mancante"}), 400

    content = data.get("content", "").strip()
    input_type = data.get("input_type", "text")
    analysis_type = data.get("analysis_type", "ontological")
    user_context = data.get("user_context", "").strip()
    project_context = data.get("project_context", "").strip()

    if len(content) < 10:
        return jsonify({"error": "Contenuto troppo breve"}), 400

    prompt = build_analysis_prompt(
        content=content,
        input_type=input_type,
        analysis_type=analysis_type,
        user_context=user_context,
        project_context=project_context
    )

    result = call_clean_debug(prompt, api_key, "route")
    return jsonify({"result": result})


@app.route("/api/synthesize", methods=["POST"])
def synthesize():
    data = request.json or {}

    api_key = data.get("anthropic_key") or ANTHROPIC_API_KEY
    if not api_key:
        return jsonify({"error": "Chiave API Anthropic mancante"}), 400

    analyses = data.get("analyses", [])
    project_context = data.get("project_context", "")
    user_context = data.get("user_context", "")

    prompt = build_synthesis_prompt(
        analyses=analyses,
        project_context=project_context,
        user_context=user_context
    )

    result = call_clean_debug(prompt, api_key, "route")
    return jsonify({"result": result})


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json or {}

    api_key = data.get("anthropic_key") or ANTHROPIC_API_KEY
    if not api_key:
        return jsonify({"error": "Chiave API Anthropic mancante"}), 400

    message = data.get("message", "").strip()
    project_state = data.get("project_state", "")
    history = data.get("history", [])

    if not message:
        return jsonify({"error": "Messaggio vuoto"}), 400

    prompt = f"""
Sei la guida interna di Media Lens v4.

Media Lens non è un chatbot generico: è uno spazio di lavoro per leggere la relazione tra utente, contenuti, analisi e sintesi.

Tono di voce:
- accogliente;
- neutrale;
- disponibile;
- chiaro;
- competente;
- orientato al progetto;
- mai aggressivo;
- mai compiacente in modo vuoto.

Devi aiutare l'utente a capire:
1. cosa può fare ora;
2. cosa può migliorare;
3. cosa può conoscere meglio;
4. quali relazioni emergono tra i materiali nel canvas;
5. quale prossimo passo operativo ha senso.

Usa il materiale del canvas come memoria del progetto.
Non inventare contenuti assenti.
Se manca qualcosa, dillo in modo semplice.
Quando serve, fai una sola domanda utile.

STATO DEL PROGETTO:
{project_state}

STORIA RECENTE:
{history}

MESSAGGIO UTENTE:
{message}
"""

    result = call_clean_debug(prompt, api_key, "route")
    return jsonify({"result": result})


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "4.0.0"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
