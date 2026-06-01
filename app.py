<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Media Lens — Voce</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:monospace;background:#111;color:#ccc;height:100vh;display:flex;flex-direction:column;overflow:hidden;font-size:12px}
.topbar{height:36px;background:#0a0a0a;border-bottom:1px solid #222;display:flex;align-items:center;padding:0 12px;gap:10px;flex-shrink:0}
.tb-logo{color:#e94560;letter-spacing:.15em;font-size:11px;text-decoration:none}
.tb-title{color:#555;font-size:11px}
.tb-right{margin-left:auto;display:flex;gap:6px;align-items:center}
.tb-btn{padding:3px 10px;border:1px solid #333;background:transparent;color:#666;font-size:10px;cursor:pointer;font-family:monospace}
.tb-btn:hover{color:#ccc;border-color:#555}
.tb-btn.red{background:#e94560;border-color:#e94560;color:#fff}
.api-input{background:#0a0a0a;border:1px solid #222;color:#555;padding:3px 8px;font-size:10px;font-family:monospace;width:200px;outline:none}
.api-input:focus{border-color:#444;color:#ccc}

.body{flex:1;display:grid;grid-template-columns:1fr 280px;overflow:hidden}

/* LEFT */
.left{display:flex;flex-direction:column;overflow:hidden;border-right:1px solid #1a1a1a}
.topic-bar{padding:8px 14px;border-bottom:1px solid #1a1a1a;background:#0a0a0a}
.topic-input{width:100%;background:transparent;border:none;color:#555;font-size:11px;font-family:monospace;outline:none}
.topic-input:focus{color:#ccc}
.topic-input::placeholder{color:#2a2a2a}

.conversation{flex:1;overflow-y:auto;padding:16px 20px;display:flex;flex-direction:column;gap:14px}
.conv-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:16px;color:#2a2a2a;text-align:center;font-size:10px;letter-spacing:.1em;line-height:1.8}

.msg{display:flex;flex-direction:column;gap:3px;animation:msgIn .2s ease}
@keyframes msgIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.msg-label{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:#333}
.msg-text{font-size:13px;line-height:1.7;color:#bbb;font-family:Georgia,serif}
.msg.user .msg-label{color:#4f8ef7;text-align:right}
.msg.user .msg-text{color:#ccc;text-align:right}
.msg.ai .msg-label{color:#7c6af7}
.msg.ai .msg-text{color:#888;font-style:italic}
.msg.error .msg-text{color:#e94560;font-size:11px;font-family:monospace;font-style:normal}

.live-transcript{padding:6px 20px;min-height:24px;font-size:11px;color:#3a3a3a;font-style:italic;flex-shrink:0;background:#0a0a0a;font-family:Georgia,serif}

/* VOICE CONTROL */
.voice-control{padding:14px 20px 16px;border-top:1px solid #1a1a1a;display:flex;align-items:center;justify-content:center;gap:40px;flex-shrink:0;background:#0a0a0a}

/* AI circle */
.ai-circle{display:flex;flex-direction:column;align-items:center;gap:6px}
.ai-ring{width:52px;height:52px;border-radius:50%;border:1px solid #1e1e1e;position:relative;display:flex;align-items:center;justify-content:center;transition:border-color .3s}
.ai-ring.speaking{border-color:rgba(124,106,247,.4)}
.ai-core{width:26px;height:26px;border-radius:50%;background:#111;border:1px solid #1e1e1e;transition:border-color .3s}
.ai-ring.speaking .ai-core{border-color:#7c6af7}
.ai-wave{position:absolute;inset:0;border-radius:50%;border:1px solid rgba(124,106,247,.3);opacity:0}
.ai-ring.speaking .ai-wave{animation:aiw 1.4s infinite;opacity:1}
.ai-ring.speaking .ai-wave:nth-child(2){animation-delay:.5s}
@keyframes aiw{0%{transform:scale(1);opacity:.5}100%{transform:scale(1.7);opacity:0}}
.ai-label{font-size:9px;color:#333;letter-spacing:.08em}
.ai-ring.speaking + .ai-label{color:#7c6af7}

/* MIC */
.mic-wrap{display:flex;flex-direction:column;align-items:center;gap:6px}
.mic-btn{width:52px;height:52px;border-radius:50%;border:1px solid #2a2a2a;background:#0a0a0a;cursor:pointer;display:flex;align-items:center;justify-content:center;position:relative;transition:border-color .2s}
.mic-btn:hover:not(:disabled){border-color:#444}
.mic-btn:disabled{opacity:.4;cursor:not-allowed}
.mic-btn.on{border-color:#e94560;background:rgba(233,69,96,.05)}
.mic-btn.on::after{content:'';position:absolute;inset:-5px;border-radius:50%;border:1px solid rgba(233,69,96,.2);animation:mr 1.3s infinite}
@keyframes mr{0%{transform:scale(1);opacity:.6}100%{transform:scale(1.5);opacity:0}}
.mic-svg{width:22px;height:22px;fill:none;stroke:#555;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;transition:stroke .2s}
.mic-btn.on .mic-svg{stroke:#e94560}
.mic-btn:disabled .mic-svg{stroke:#333}
.mic-label{font-size:9px;color:#333;letter-spacing:.08em;text-align:center;min-width:80px}
.mic-btn.on + .mic-label{color:#e94560}

/* RIGHT */
.right{display:flex;flex-direction:column;overflow:hidden;background:#0a0a0a}
.right-header{padding:8px 12px;border-bottom:1px solid #1a1a1a;font-size:9px;color:#333;letter-spacing:.1em;text-transform:uppercase;flex-shrink:0}
.right-body{flex:1;overflow-y:auto;padding:8px}
.right-empty{color:#222;font-size:10px;letter-spacing:.08em;padding:24px 12px;text-align:center;line-height:1.8}
.ab{border-left:2px solid;padding:8px 10px;margin-bottom:6px;background:#0d0d0d;animation:fadeIn .3s}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.ab.claim{border-color:#e94560}
.ab.rhetoric{border-color:#f59e0b}
.ab.omission{border-color:#7c6af7}
.ab.verified{border-color:#22c55e}
.ab-tag{font-size:9px;letter-spacing:.08em;text-transform:uppercase;padding:1px 6px;border:1px solid;color:#666;display:inline-block;margin-bottom:5px}
.ab-tag.claim{border-color:#e94560}
.ab-tag.rhetoric{border-color:#f59e0b}
.ab-tag.omission{border-color:#7c6af7}
.ab-tag.verified{border-color:#22c55e}
.ab-text{font-size:10px;color:#555;line-height:1.5}
.right-footer{padding:8px 12px;border-top:1px solid #1a1a1a;flex-shrink:0}
.rf-btn{width:100%;padding:6px;border:1px solid #1e1e1e;background:transparent;color:#333;font-size:10px;cursor:pointer;font-family:monospace}
.rf-btn:hover{color:#888;border-color:#444}
::-webkit-scrollbar{width:3px}::-webkit-scrollbar-track{background:#0a0a0a}::-webkit-scrollbar-thumb{background:#1e1e1e}
</style>
</head>
<body>
<div class="topbar">
  <a href="/" class="tb-logo">ML·</a>
  <span class="tb-title">voce</span>
  <div class="tb-right">
    <input class="api-input" id="apiKey" type="password" placeholder="sk-ant-... (opzionale)"/>
    <button class="tb-btn" onclick="resetAll()">reset</button>
    <button class="tb-btn red" onclick="endSession()">chiudi → canvas</button>
  </div>
</div>

<div class="body">
  <div class="left">
    <div class="topic-bar">
      <input class="topic-input" id="topicInput" placeholder="argomento — opzionale"/>
    </div>
    <div class="conversation" id="conversation">
      <div class="conv-empty" id="convEmpty">
        premi il microfono e parla<br>
        l'AI risponde e analizza
      </div>
    </div>
    <div class="live-transcript" id="liveTranscript"></div>
    <div class="voice-control">
      <div class="ai-circle">
        <div class="ai-ring" id="aiRing">
          <div class="ai-wave"></div>
          <div class="ai-wave"></div>
          <div class="ai-core"></div>
        </div>
        <div class="ai-label" id="aiLabel">AI</div>
      </div>
      <div class="mic-wrap">
        <button class="mic-btn" id="micBtn" onclick="toggleMic()">
          <svg class="mic-svg" viewBox="0 0 24 24">
            <rect x="9" y="2" width="6" height="11" rx="3"/>
            <path d="M5 11a7 7 0 0 0 14 0"/>
            <line x1="12" y1="18" x2="12" y2="22"/>
            <line x1="8" y1="22" x2="16" y2="22"/>
          </svg>
        </button>
        <div class="mic-label" id="micLabel">premi per parlare</div>
      </div>
    </div>
  </div>

  <div class="right">
    <div class="right-header">// analisi</div>
    <div class="right-body" id="rightBody">
      <div class="right-empty" id="rightEmpty">// i punti critici<br>appaiono qui</div>
    </div>
    <div class="right-footer">
      <button class="rf-btn" onclick="endSession()">genera report →</button>
    </div>
  </div>
</div>

<script>
let micOn=false,thinking=false,buffer='';
let rec=null,synth=window.speechSynthesis;
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;

function getKey(){ return document.getElementById('apiKey').value.trim(); }
function getTopic(){ return document.getElementById('topicInput').value.trim()||'discussione aperta'; }

function toggleMic(){
  if(thinking) return;
  if(micOn) stopMic();
  else startMic();
}

function startMic(){
  micOn=true; buffer='';
  document.getElementById('micBtn').classList.add('on');
  setMicLabel('in ascolto');

  if(SR){
    rec=new SR();
    rec.lang='it-IT'; rec.continuous=true; rec.interimResults=true;
    rec.onresult=e=>{
      let interim='',final='';
      for(let i=e.resultIndex;i<e.results.length;i++){
        if(e.results[i].isFinal) final+=e.results[i][0].transcript+' ';
        else interim+=e.results[i][0].transcript;
      }
      if(final) buffer+=final;
      document.getElementById('liveTranscript').textContent=(buffer+interim).trim()||'';
    };
    rec.onerror=e=>{
      if(e.error==='not-allowed'){addMsg('error','Permesso microfono negato. Abilita il microfono nelle impostazioni del browser.');}
      stopMicSilent();
    };
    rec.onend=()=>{if(micOn&&rec) try{rec.start();}catch(e){}};
    try{rec.start();}catch(e){addMsg('error','Microfono non disponibile: '+e.message); stopMicSilent();}
  } else {
    addMsg('error','Riconoscimento vocale non supportato. Usa Chrome o Edge.');
    stopMicSilent();
  }
}

function stopMicSilent(){
  micOn=false;
  if(rec){try{rec.stop();}catch(e){} rec=null;}
  document.getElementById('micBtn').classList.remove('on');
  setMicLabel('premi per parlare');
}

function stopMic(){
  micOn=false;
  if(rec){try{rec.stop();}catch(e){} rec=null;}
  document.getElementById('micBtn').classList.remove('on');
  const text=buffer.trim();
  document.getElementById('liveTranscript').textContent='';
  buffer='';
  if(text.length>3) processUser(text);
  else setMicLabel('premi per parlare');
}

async function processUser(text){
  thinking=true;
  document.getElementById('micBtn').disabled=true;
  addMsg('user',text);
  setMicLabel('elaboro...');

  try{
    const resp=await fetch('/api/voce/turno',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text,topic:getTopic(),anthropic_key:getKey()})
    });
    const data=await resp.json();
    if(data.error) throw new Error(data.error);
    addMsg('ai',data.reply);
    (data.analysis||[]).forEach(a=>addAnalysis(a));
    speakAI(data.reply);
  } catch(e){
    addMsg('error','Errore: '+e.message);
    afterAI();
  }
}

function addMsg(role,text){
  document.getElementById('convEmpty')?.remove();
  const conv=document.getElementById('conversation');
  const div=document.createElement('div');
  div.className='msg '+role;
  const label={user:'tu',ai:'AI',error:'errore'}[role]||role;
  div.innerHTML=`<div class="msg-label">${label}</div><div class="msg-text">${text}</div>`;
  conv.appendChild(div);
  conv.scrollTop=conv.scrollHeight;
}

function addAnalysis(a){
  document.getElementById('rightEmpty')?.remove();
  const body=document.getElementById('rightBody');
  const label={claim:'claim',rhetoric:'retorica',omission:'omissione',verified:'verificato'}[a.type]||a.type;
  const div=document.createElement('div');
  div.className='ab '+a.type;
  div.innerHTML=`<span class="ab-tag ${a.type}">${label}</span><div class="ab-text">${a.text}</div>`;
  body.insertBefore(div,body.firstChild);
}

function speakAI(text){
  document.getElementById('aiRing').classList.add('speaking');
  document.getElementById('aiLabel').textContent='risponde';
  setMicLabel('AI sta parlando');

  if(synth&&synth.speak){
    const utt=new SpeechSynthesisUtterance(text);
    utt.lang='it-IT'; utt.rate=0.92;
    const voices=synth.getVoices().filter(v=>v.lang.startsWith('it'));
    if(voices.length) utt.voice=voices[0];
    utt.onend=afterAI;
    utt.onerror=afterAI;
    synth.cancel();
    synth.speak(utt);
  } else {
    setTimeout(afterAI, Math.min(text.length*45, 8000));
  }
}

function afterAI(){
  thinking=false;
  document.getElementById('micBtn').disabled=false;
  document.getElementById('aiRing').classList.remove('speaking');
  document.getElementById('aiLabel').textContent='AI';
  setMicLabel('premi per rispondere');
}

function setMicLabel(t){ document.getElementById('micLabel').textContent=t; }

function endSession(){
  if(synth) synth.cancel();
  const count=document.querySelectorAll('.ab').length;
  alert('// Sessione terminata.\n'+count+' punti critici rilevati\n\n→ Aggiunto al canvas come nodo conversazione');
}

function resetAll(){
  if(synth) synth.cancel();
  if(rec){try{rec.stop();}catch(e){} rec=null;}
  micOn=false; thinking=false; buffer='';
  document.getElementById('micBtn').classList.remove('on');
  document.getElementById('micBtn').disabled=false;
  document.getElementById('aiRing').classList.remove('speaking');
  document.getElementById('aiLabel').textContent='AI';
  setMicLabel('premi per parlare');
  document.getElementById('conversation').innerHTML='<div class="conv-empty" id="convEmpty">premi il microfono e parla<br>l\'AI risponde e analizza</div>';
  document.getElementById('rightBody').innerHTML='<div class="right-empty" id="rightEmpty">// i punti critici<br>appaiono qui</div>';
  document.getElementById('liveTranscript').textContent='';
  document.getElementById('topicInput').value='';
}
</script>
</body>
</html>
