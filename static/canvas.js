console.log("Media Lens canvas.js operativo");

window.addEventListener("load", () => {
  const canvas = document.getElementById("canvas");
  const leftPanel = document.getElementById("leftPanel");
  const lpViews = document.getElementById("lpViews");

  if (!canvas || !leftPanel || !lpViews) return;

  // PANNELLO SINISTRO SEMPLICE
  const style = document.createElement("style");
  style.textContent = `
    .node.loading-analysis { animation: mlNodePulse 1s infinite; border-color: var(--acc2)!important; }
    @keyframes mlNodePulse { 0%,100%{box-shadow:0 0 0 0 rgba(139,130,232,.28)} 50%{box-shadow:0 0 0 6px rgba(139,130,232,.08)} }

    #leftPanel.open { width:300px!important; }
    #leftPanel .lp-viewport { height:100%!important; overflow:hidden auto!important; }
    #leftPanel .lp-views { position:static!important; transform:none!important; transition:none!important; height:100%!important; }
    #leftPanel .lp-view { display:none!important; height:100%!important; overflow:hidden auto!important; }
    #leftPanel .lp-view.active-view { display:flex!important; }
  `;
  document.head.appendChild(style);

  const views = ["input", "analisi", "nota", "chat"];

  function showPanel(name) {
    leftPanel.classList.add("open");
    views.forEach(v => {
      document.getElementById("view-" + v)?.classList.toggle("active-view", v === name);
      document.getElementById("btn-" + v)?.classList.toggle("active", v === name);
    });
  }

  views.forEach(v => {
    const btn = document.getElementById("btn-" + v);
    if (btn) btn.onclick = e => {
      e.preventDefault();
      e.stopPropagation();
      showPanel(v);
    };
  });

  // INTENZIONE OBBLIGATORIA
  const inputView = document.getElementById("view-input");
  if (inputView && !document.getElementById("inputIntent")) {
    const addBtn = inputView.querySelector(".add-btn");
    const label = document.createElement("label");
    label.className = "view-label";
    label.style.marginTop = "10px";
    label.textContent = "Intenzione dell'analisi · obbligatoria";

    const intent = document.createElement("textarea");
    intent.id = "inputIntent";
    intent.className = "input-field";
    intent.rows = 3;
    intent.placeholder = "Perché stai portando questo contenuto? Cosa vuoi capire o mettere a distanza?";

    inputView.insertBefore(label, addBtn);
    inputView.insertBefore(intent, addBtn);
  }

  // PANNELLO ANALISI
  const analysisView = document.getElementById("view-analisi");
  if (analysisView) {
    analysisView.innerHTML = `
      <div class="view-title">Analizza input</div>
      <div style="background:var(--panel);border:0.5px solid var(--brd);border-radius:8px;padding:12px;margin-bottom:12px;">
        <div style="font-size:13px;font-weight:500;color:var(--txt1);margin-bottom:5px;">Seleziona un input da analizzare</div>
        <div style="font-size:10px;font-family:var(--mono);color:var(--txt3);line-height:1.5;">
          L'AI userà contenuto, tipo e intenzione dichiarata per costruire automaticamente una lettura calibrata.
        </div>
      </div>
      <div class="analysis-list">
        ${[
          ["ontologica","che cosa è"],
          ["strutturale","come è costruito"],
          ["retorica","come orienta"],
          ["epistemica","che conoscenza produce"],
          ["assenze","cosa manca"],
          ["relazionale","che rapporto apre"],
          ["trasformativa","cosa può modificare"],
          ["contestuale","con cosa si relaziona"]
        ].map((a,i)=>`
          <div class="analysis-item ${i===0 ? "active" : ""}" data-analysis="${a[0]}">
            <div><div class="analysis-name">${a[0]}</div><div class="analysis-sub">${a[1]}</div></div>
            <div class="analysis-status ${i===0 ? "status-run" : "status-none"}"></div>
          </div>
        `).join("")}
      </div>
      <button class="add-btn" id="runAnalysisBtn" style="margin-top:12px;">Avvia analisi selezionata</button>
    `;

    analysisView.querySelectorAll(".analysis-item").forEach(item => {
      item.onclick = () => {
        analysisView.querySelectorAll(".analysis-item").forEach(i => {
          i.classList.remove("active");
          i.querySelector(".analysis-status").className = "analysis-status status-none";
        });
        item.classList.add("active");
        item.querySelector(".analysis-status").className = "analysis-status status-run";
      };
    });

    document.getElementById("runAnalysisBtn").onclick = async () => {
      
const selectedNode = document.querySelector(".node.active");
if (!selectedNode) {
  alert("Seleziona prima un input nel canvas.");
  return;
}

const analysisName = analysisView.querySelector(".analysis-item.active")?.dataset.analysis || "ontologica";
const content = selectedNode.dataset.content || "";
const intent = selectedNode.dataset.intent || "";

const analysisNode = document.createElement("div");
analysisNode.className = "node loading-analysis";
analysisNode.style.left = "320px";
analysisNode.style.top = "140px";
analysisNode.style.width = "170px";
analysisNode.dataset.content = "Analisi in corso...";
analysisNode.innerHTML = `
  <div class="node-type">analisi · ${analysisName}</div>
  <div class="node-title">Caricamento...</div>
`;
document.getElementById("canvasLayer").appendChild(analysisNode);

if (typeof window.drawEdges === "function") window.drawEdges();

document.getElementById("inspectorPanel")?.classList.add("open");
document.getElementById("inspectorPanel").style.height = "340px";
document.getElementById("btn-inspector")?.classList.add("active");
document.getElementById("ispType").textContent = "analisi · " + analysisName;
document.getElementById("ispTitle").textContent = "Analisi in corso";
document.getElementById("ispContent").textContent = "Media Lens sta costruendo la giusta distanza tra utente e contenuto.";

let progress = 0;
const progressBox = document.createElement("div");
progressBox.id = "analysisProgressBox";
progressBox.style.marginTop = "12px";
progressBox.innerHTML = `
  <div style="font-size:10px;font-family:var(--mono);color:var(--txt3);margin-bottom:6px;">analisi in corso</div>
  <div style="height:5px;background:var(--cv);border-radius:999px;overflow:hidden;">
    <div id="analysisProgressBar" style="height:100%;width:0%;background:var(--acc);transition:width .25s ease;"></div>
  </div>
  <div style="display:flex;align-items:center;margin-top:8px;gap:8px;">
    <span id="analysisProgressText" style="font-size:11px;font-family:var(--mono);color:var(--acc);">0%</span>
    <button id="cancelAnalysisBtn" style="margin-left:auto;height:24px;padding:0 8px;border:none;border-radius:4px;background:var(--brd2);color:var(--txt2);font-size:10px;">annulla</button>
    <button id="viewAnalysisBtn" disabled style="height:24px;padding:0 8px;border:none;border-radius:4px;background:var(--acc);color:white;font-size:10px;opacity:.35;">vedi analisi</button>
  </div>
`;

const existing = document.getElementById("analysisProgressBox");
if (existing) existing.remove();
analysisView.appendChild(progressBox);

let cancelled = false;
document.getElementById("cancelAnalysisBtn").onclick = () => {
  cancelled = true;
  analysisNode.remove();
  progressBox.remove();
};

const fakeProgress = setInterval(() => {
  if (cancelled) {
    clearInterval(fakeProgress);
    return;
  }
  progress = Math.min(90, progress + Math.floor(Math.random() * 9) + 3);
  document.getElementById("analysisProgressBar").style.width = progress + "%";
  document.getElementById("analysisProgressText").textContent = progress + "%";
}, 350);

try {
  const res = await fetch("/api/analyze", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      input_type: selectedNode.querySelector(".node-type")?.textContent || "testo",
      analysis_type: analysisName,
      content: content,
      user_context: intent,
      project_context: ""
    })
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Errore analisi");

  clearInterval(fakeProgress);
  progress = 100;
  document.getElementById("analysisProgressBar").style.width = "100%";
  document.getElementById("analysisProgressText").textContent = "100%";

  analysisNode.classList.remove("loading-analysis");
  analysisNode.classList.add("done");
  analysisNode.querySelector(".node-title").textContent = "Analisi " + analysisName;
  analysisNode.dataset.content = data.result;

  const viewBtn = document.getElementById("viewAnalysisBtn");
  viewBtn.disabled = false;
  viewBtn.style.opacity = "1";
  viewBtn.onclick = () => {
    progressBox.style.transition = "opacity .35s ease, transform .35s ease";
    progressBox.style.opacity = "0";
    progressBox.style.transform = "translateY(-4px)";
    setTimeout(() => progressBox.remove(), 360);

    document.getElementById("ispType").textContent = "analisi · " + analysisName;
    document.getElementById("ispTitle").textContent = "Analisi " + analysisName;
    document.getElementById("ispContent").textContent = data.result;
  };

} catch (err) {
  clearInterval(fakeProgress);
  analysisNode.classList.remove("loading-analysis");
  analysisNode.classList.add("alert");
  analysisNode.querySelector(".node-title").textContent = "Errore analisi";
  analysisNode.dataset.content = err.message;
  document.getElementById("ispContent").textContent = "Errore: " + err.message;
}

    };
  }

  // CANVAS
  let panX = 0, panY = 0, zoom = 1;
  let selected = new Set();
  let mode = null;
  let start = null;

  const layer = document.createElement("div");
  layer.id = "canvasLayer";
  layer.style.position = "absolute";
  layer.style.left = "0";
  layer.style.top = "0";
  layer.style.width = "3000px";
  layer.style.height = "3000px";
  layer.style.transformOrigin = "0 0";

  while (canvas.firstChild) layer.appendChild(canvas.firstChild);
  canvas.appendChild(layer);

  const edgeSvg = layer.querySelector("#edges-svg");

  window.drawEdges = function () {
    if (!edgeSvg) return;
    function r(id) {
      const el = document.getElementById(id);
      if (!el) return null;
      const x = parseFloat(el.style.left || 0);
      const y = parseFloat(el.style.top || 0);
      const w = el.offsetWidth;
      const h = el.offsetHeight;
      return { x1:x, x2:x+w, y1:y, y2:y+h, mx:x+w/2, my:y+h/2, cx:x+w/2, cy:y+h/2, cr:w/2 };
    }
    function bez(x1,y1,x2,y2,c,o) {
      const dx=(x2-x1)*.5;
      return `<path d="M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}" stroke="${c}" stroke-width="1" fill="none" opacity="${o}"/>`;
    }
    const n0=r("n0"), n1=r("n1"), n2=r("n2"), n3=r("n3"), n4=r("n4");
    if(!n0||!n1||!n2||!n3||!n4) return;
    const s4x=n4.cx-n4.cr, s4y=n4.cy;
    edgeSvg.innerHTML =
      bez(n0.x2,n0.my,n2.x1,n2.my,"#B0ACA4",".85") +
      bez(n1.x2,n1.my,n3.x1,n3.my,"#B0ACA4",".85") +
      bez(n0.x2,n0.my,n3.x1,n3.my,"#B0ACA4",".3") +
      bez(n2.x2,n2.my,s4x,s4y,"#8B82E8",".7") +
      bez(n3.x2,n3.my,s4x,s4y,"#8B82E8",".7");
  };

  function nodes() {
    return [...layer.querySelectorAll(".node,.nota-node,.synth-node")];
  }

  function apply() {
    layer.style.transform = `translate(${panX}px,${panY}px) scale(${zoom})`;
    window.drawEdges();
  }

  document.getElementById("btn-fit")?.addEventListener("click", () => {
    panX = 0; panY = 0; zoom = 1; apply();
  });

  function world(e) {
    const r = canvas.getBoundingClientRect();
    return { x:(e.clientX-r.left-panX)/zoom, y:(e.clientY-r.top-panY)/zoom };
  }

  function clearSel() {
    selected.forEach(n => n.classList.remove("active"));
    selected.clear();
  }

  function select(n, add=false) {
    if (!add) clearSel();
    selected.add(n);
    n.classList.add("active");
  }

  function attach(n) {
    if (n.dataset.ready) return;
    n.dataset.ready = "1";

    n.onmousedown = e => {
      if (e.button !== 0) return;
      e.stopPropagation();

      if (e.shiftKey) {
        if (selected.has(n)) { selected.delete(n); n.classList.remove("active"); }
        else select(n, true);
      } else if (!selected.has(n)) select(n);

      const p = world(e);
      start = {
        x:p.x, y:p.y,
        original:[...selected].map(el => ({ el, x:parseFloat(el.style.left||0), y:parseFloat(el.style.top||0) }))
      };
      mode = "drag";
    };

    n.ondblclick = e => {
      e.stopPropagation();
      document.getElementById("ispType").textContent = n.querySelector(".node-type,.nota-label,.synth-label")?.textContent || "nodo";
      document.getElementById("ispTitle").textContent = n.querySelector(".node-title,.nota-text,.synth-label")?.textContent || "Nodo";
      document.getElementById("ispContent").textContent = n.dataset.content || "Nessun contenuto.";
      document.getElementById("inspectorPanel")?.classList.add("open");
      document.getElementById("btn-inspector")?.classList.add("active");
    };
  }

  nodes().forEach(attach);

  canvas.onmousedown = e => {
    if (e.target !== canvas && e.target !== layer) return;
    clearSel();
    mode = "pan";
    start = { x:e.clientX, y:e.clientY, panX, panY };
  };

  document.onmousemove = e => {
    if (!mode || !start) return;

    if (mode === "pan") {
      panX = start.panX + e.clientX - start.x;
      panY = start.panY + e.clientY - start.y;
      apply();
    }

    if (mode === "drag") {
      const p = world(e);
      const dx = p.x - start.x;
      const dy = p.y - start.y;
      start.original.forEach(o => {
        o.el.style.left = o.x + dx + "px";
        o.el.style.top = o.y + dy + "px";
      });
      window.drawEdges();
    }
  };

  document.onmouseup = () => { mode = null; start = null; };

  canvas.onwheel = e => {
    e.preventDefault();
    const before = world(e);
    zoom = Math.max(.25, Math.min(2.5, zoom * (e.deltaY < 0 ? 1.08 : .92)));
    const r = canvas.getBoundingClientRect();
    panX = e.clientX - r.left - before.x * zoom;
    panY = e.clientY - r.top - before.y * zoom;
    apply();
  };

  const addBtn = document.querySelector(".add-btn");
  if (addBtn) {
    addBtn.onclick = e => {
      e.preventDefault();
      const view = document.getElementById("view-input");
      const type = view.querySelector("select")?.value || "input";
      const fields = view.querySelectorAll(".input-field");
      const content = fields[0]?.value.trim() || "";
      const title = fields[1]?.value.trim() || content.slice(0,28) || "Nuovo input";
      const intent = document.getElementById("inputIntent")?.value.trim() || "";

      if (!content) return alert("Inserisci il contenuto.");
      if (!intent) return alert("Inserisci l'intenzione dell'analisi.");

      const n = document.createElement("div");
      n.className = "node";
      n.style.left = "120px";
      n.style.top = "120px";
      n.style.width = "150px";
      n.dataset.content = content;
      n.dataset.intent = intent;
      n.innerHTML = `<div class="node-type">${type}</div><div class="node-title">${title}</div>`;
      layer.appendChild(n);
      attach(n);
      select(n);
      apply();

      fields.forEach(f => f.value = "");
      document.getElementById("inputIntent").value = "";
    };
  }

  apply();
});
