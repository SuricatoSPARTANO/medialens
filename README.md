# Media Lens — Analisi critica dei contenuti

Strumento open source per analizzare in tempo reale contenuti media:
claim non verificati, framing emotivo, bias ideologico, tecniche retoriche, omissioni.

## Modalità supportate

- **Testo / Post social** — incolla qualsiasi testo
- **Link video** — YouTube, Instagram Reels, TikTok, podcast (richiede OpenAI per trascrizione)
- **Trascrizione** — incolla trascrizioni già pronte
- **Articolo** — analisi di notizie e articoli
- **Live** — analisi in tempo reale via microfono (dibattiti, discorsi, conferenze)

## Requisiti

- Python 3.10+
- ffmpeg installato nel sistema (`brew install ffmpeg` su Mac, `apt install ffmpeg` su Linux)
- Chiave API Anthropic (obbligatoria)
- Chiave API OpenAI (opzionale, solo per analisi video/audio)

## Avvio locale

```bash
# 1. Installa dipendenze
pip install -r requirements.txt

# 2. (Opzionale) variabili d'ambiente per non inserire le chiavi ogni volta
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...

# 3. Avvia
python app.py

# Apri http://localhost:5000
```

## Deploy su Railway (gratuito)

1. Crea account su https://railway.app
2. "New Project" → "Deploy from GitHub repo"
3. Carica questa cartella su un repo GitHub
4. Railway rileva automaticamente il Procfile e deploya
5. Aggiungi le variabili d'ambiente in Railway:
   - `ANTHROPIC_API_KEY` = la tua chiave
   - `OPENAI_API_KEY` = la tua chiave OpenAI (opzionale)
6. Il tuo URL pubblico sarà tipo `medialens.railway.app`

## Deploy su Render (gratuito)

1. Crea account su https://render.com
2. "New Web Service" → connetti GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120`
5. Aggiungi le variabili d'ambiente nel pannello Render

## Costi indicativi API

| Utilizzo | Anthropic | OpenAI Whisper | Totale |
|---|---|---|---|
| 100 analisi testo/mese | ~0.30€ | — | ~0.30€ |
| 100 analisi video 5min/mese | ~0.30€ | ~3.00€ | ~3.30€ |
| 500 analisi miste/mese | ~1.50€ | ~5.00€ | ~6.50€ |

## Struttura progetto

```
medialens/
├── app.py              # Backend Flask
├── templates/
│   └── index.html      # Frontend completo
├── requirements.txt
├── Procfile            # Per Railway/Render
└── README.md
```

## Note sulla modalità Live

La modalità live usa la Web Speech API del browser (gratuita, nessun costo API).
Funziona meglio su Chrome o Edge. Ogni ~20 secondi il testo accumulato viene
inviato a Claude per l'analisi — i risultati appaiono in tempo reale.

Per dibattiti in luoghi pubblici: avvicina il microfono o usa un microfono esterno
per migliorare la qualità della trascrizione.
