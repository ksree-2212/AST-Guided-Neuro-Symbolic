/**
 * AST-Guided Neuro-Symbolic RAG & Migration Studio Frontend
 * Interactive graph visualizer, dual-memory retrieval explorer, and compiler integration
 */

// Application State
const state = {
  activeFilename: "BILLING.cbl",
  sourceCode: "",
  parsedData: null,
  viewMode: "dependency", // 'dependency' | 'ast' | 'dual'
  retrievalResult: null,
  selectedNode: null,
  zoom: 1.0,
  pan: { x: 0, y: 0 },
  isDragging: false,
  dragStart: { x: 0, y: 0 }
};

// DOM Elements
const sampleSelect = document.getElementById("sampleSelect");
const fileUpload = document.getElementById("fileUpload");
const folderUpload = document.getElementById("folderUpload");
const dropZone = document.getElementById("dropZone");
const codeEditor = document.getElementById("codeEditor");
const graphSvg = document.getElementById("graphSvg");
const ragQueryInput = document.getElementById("ragQueryInput");
const runQueryBtn = document.getElementById("runQueryBtn");
const compileRunBtn = document.getElementById("compileRunBtn");
const terminalOutput = document.getElementById("terminalOutput");
const generatedJavaOutput = document.getElementById("generatedJavaOutput");
const promptOutput = document.getElementById("promptOutput");
const astProposedCard = document.getElementById("astProposedCard");
const baselineCard = document.getElementById("baselineCard");
const structuralConstraintsList = document.getElementById("structuralConstraintsList");

// Initialize Studio
window.addEventListener("DOMContentLoaded", async () => {
  setupEventListeners();
  setupSvgInteractions();
  await loadSamples();
});

// Setup Events
function setupEventListeners() {
  // Sample dropdown
  sampleSelect.addEventListener("change", async (e) => {
    const filename = e.target.value;
    if (filename) {
      await loadSampleByName(filename);
    }
  });

  // File Upload
  fileUpload.addEventListener("change", (e) => handleFileUpload(e.target.files));
  folderUpload.addEventListener("change", (e) => handleFileUpload(e.target.files));

  // Drag and Drop
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files);
    }
  });

  // Source code edit re-parse on blur or Ctrl+S
  codeEditor.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      reparseCurrentCode();
    }
  });

  // View Mode Tabs
  document.querySelectorAll(".view-mode-tabs .tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".view-mode-tabs .tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.viewMode = btn.dataset.mode;
      renderGraph();
    });
  });

  // Right Pane Tabs (RAG vs Compiler vs Java)
  document.querySelectorAll(".right-pane-tabs .right-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".right-pane-tabs .right-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      
      const tabTarget = tab.dataset.tab;
      document.getElementById("tabContentRag").style.display = tabTarget === "rag" ? "flex" : "none";
      document.getElementById("tabContentPrompt").style.display = tabTarget === "prompt" ? "block" : "none";
      document.getElementById("tabContentCompiler").style.display = tabTarget === "compiler" ? "block" : "none";
    });
  });

  // Query Run
  runQueryBtn.addEventListener("click", runRagQuery);
  ragQueryInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runRagQuery();
  });

  // Compile & Run Button
  compileRunBtn.addEventListener("click", runCompiler);

  // Copy Java Code Button
  const copyBtn = document.getElementById("copyJavaBtn");
  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      const code = generatedJavaOutput.textContent;
      navigator.clipboard.writeText(code).then(() => {
        copyBtn.textContent = "Copied!";
        setTimeout(() => copyBtn.textContent = "Copy Java", 2000);
      });
    });
  }

  // Download Java File Button
  const downloadBtn = document.getElementById("downloadJavaBtn");
  if (downloadBtn) {
    downloadBtn.addEventListener("click", () => {
      const code = generatedJavaOutput.textContent;
      const blob = new Blob([code], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = (state.activeFilename.replace(/\.(cbl|cob)$/i, "") || "CobolProgram") + ".java";
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  // Zoom buttons
  document.getElementById("zoomInBtn").addEventListener("click", () => zoomGraph(1.2));
  document.getElementById("zoomOutBtn").addEventListener("click", () => zoomGraph(0.8));
  document.getElementById("zoomFitBtn").addEventListener("click", () => resetZoom());
}

// Setup SVG pan and zoom
function setupSvgInteractions() {
  const container = document.querySelector(".graph-canvas-container");

  container.addEventListener("wheel", (e) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    zoomGraph(factor);
  });

  container.addEventListener("mousedown", (e) => {
    if (e.target.tagName === 'svg' || e.target.id === 'graphGroup' || e.target.classList.contains('bg-drag')) {
      state.isDragging = true;
      state.dragStart = { x: e.clientX - state.pan.x, y: e.clientY - state.pan.y };
    }
  });

  window.addEventListener("mousemove", (e) => {
    if (state.isDragging) {
      state.pan.x = e.clientX - state.dragStart.x;
      state.pan.y = e.clientY - state.dragStart.y;
      updateSvgTransform();
    }
  });

  window.addEventListener("mouseup", () => {
    state.isDragging = false;
  });
}

function zoomGraph(factor) {
  state.zoom = Math.max(0.2, Math.min(3.0, state.zoom * factor));
  updateSvgTransform();
}

function resetZoom() {
  state.zoom = 1.0;
  state.pan = { x: 0, y: 0 };
  updateSvgTransform();
}

function updateSvgTransform() {
  const g = document.getElementById("graphGroup");
  if (g) {
    g.setAttribute("transform", `translate(${state.pan.x}, ${state.pan.y}) scale(${state.zoom})`);
  }
}

// API Calls
async function loadSamples() {
  try {
    const res = await fetch("/api/samples");
    const data = await res.json();
    sampleSelect.innerHTML = `<option value="">Select Sample...</option>`;
    data.samples.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.filename;
      opt.textContent = `${s.filename} (${s.description})`;
      sampleSelect.appendChild(opt);
    });
    // Auto select BILLING.cbl
    if (data.samples.length > 0) {
      sampleSelect.value = "BILLING.cbl";
      await loadSampleByName("BILLING.cbl");
    }
  } catch (err) {
    console.error("Failed to load samples:", err);
  }
}

async function loadSampleByName(filename) {
  try {
    const res = await fetch("/api/samples");
    const data = await res.json();
    const s = data.samples.find(item => item.filename === filename);
    if (s) {
      state.activeFilename = s.filename;
      state.sourceCode = s.content;
      codeEditor.value = s.content;
      document.getElementById("currentFileLabel").textContent = s.filename;
      await reparseCurrentCode();
    }
  } catch (err) {
    console.error("Error loading sample:", err);
  }
}

async function handleFileUpload(fileList) {
  if (!fileList || fileList.length === 0) return;
  const formData = new FormData();
  for (let i = 0; i < fileList.length; i++) {
    formData.append("files", fileList[i]);
  }

  try {
    const res = await fetch("/api/upload", {
      method: "POST",
      body: formData
    });
    const result = await res.json();
    if (result.uploaded && result.uploaded.length > 0) {
      const first = result.uploaded[0];
      state.activeFilename = first.filename;
      state.sourceCode = first.content;
      codeEditor.value = first.content;
      document.getElementById("currentFileLabel").textContent = `${first.filename} (${result.uploaded.length} files loaded)`;
      await reparseCurrentCode();
    }
  } catch (err) {
    alert("Upload failed: " + err.message);
  }
}

async function reparseCurrentCode() {
  state.sourceCode = codeEditor.value;
  try {
    const res = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: state.activeFilename,
        source_code: state.sourceCode
      })
    });
    const data = await res.json();
    state.parsedData = data;
    
    // Update summary counters
    document.getElementById("nodeCountBadge").textContent = `${data.chunks.length} Chunks / ${data.variables.length} Data`;
    document.getElementById("edgeCountBadge").textContent = `${data.edges.length} Edges`;
    
    // Render Graph
    renderGraph();
    
    // Automatically trigger initial RAG comparison query
    await runRagQuery();
  } catch (err) {
    console.error("Parse failed:", err);
  }
}

async function runRagQuery() {
  const query = ragQueryInput.value.trim() || "compute total cost including tax";
  try {
    runQueryBtn.textContent = "...";
    const res = await fetch("/api/rag-search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        top_k: 2,
        max_hops: 2,
        target_language: "Java"
      })
    });
    const data = await res.json();
    state.retrievalResult = data;
    renderRagResults(data);
    if (state.viewMode === "dual") {
      renderGraph();
    }
  } catch (err) {
    console.error("RAG search failed:", err);
  } finally {
    runQueryBtn.textContent = "Run";
  }
}

function renderRagResults(data) {
  // 1. Proposed AST-Guided Retrieval Card
  const proposed = data.ast_retrieval;
  let proposedHtml = `
    <div class="card-title-row">
      <h4>AST-Guided Neuro-Symbolic RAG</h4>
      <span class="badge badge-green">${proposed.total_retrieved} Recovered</span>
    </div>
    <p style="font-size: 11px; color: var(--text-muted); margin-bottom: 10px;">
      Entry points matched via vector embeddings, then complete dependency closures recovered via bounded graph traversal.
    </p>
  `;

  proposed.bundle.forEach(item => {
    const isEntry = item.reason === "vector_match";
    const badgeClass = isEntry ? "tag-match" : "tag-dep";
    const label = isEntry ? `VECTOR MATCH (score: ${item.score})` : `GRAPH DEPENDENCY`;
    const cleanId = item.id.split("::").slice(1).join("::") || item.id;
    proposedHtml += `
      <div class="retrieved-item">
        <span class="tag ${badgeClass}">${label}</span>
        <strong>${cleanId}</strong>
        <div style="color: var(--text-dim); margin-top: 4px; font-size: 10.5px;">${item.type}</div>
      </div>
    `;
  });
  astProposedCard.innerHTML = proposedHtml;

  // 2. Structural Constraints summary
  let constraintsHtml = `<div style="font-size: 12px; font-weight: 600; margin-bottom: 6px; color: var(--accent-amber);">Structural Constraints Derived:</div>`;
  if (proposed.constraint_lines && proposed.constraint_lines.length > 0) {
    constraintsHtml += `<ul style="font-family: var(--font-mono); font-size: 11.5px; padding-left: 18px; color: #fde68a;">`;
    proposed.constraint_lines.forEach(c => {
      constraintsHtml += `<li style="margin-bottom: 4px;">${c}</li>`;
    });
    constraintsHtml += `</ul>`;
  } else {
    constraintsHtml += `<p style="font-size: 11px; color: var(--text-dim);">No inter-chunk dependencies detected</p>`;
  }
  structuralConstraintsList.innerHTML = constraintsHtml;

  // 3. Baseline Fixed-Size Chunking Card
  const baseline = data.baseline_retrieval;
  let baselineHtml = `
    <div class="card-title-row">
      <h4>Standard RAG Baseline (4-line chunks)</h4>
      <span class="badge badge-red">Severed & Incomplete</span>
    </div>
    <p style="font-size: 11px; color: var(--text-muted); margin-bottom: 10px;">
      Fixed windows cut functions across lines; no awareness of CALLS or DATA dependencies.
    </p>
  `;

  baseline.retrieved_windows.forEach(w => {
    baselineHtml += `
      <div class="retrieved-item" style="border-left: 3px solid var(--accent-rose);">
        <span class="tag tag-severed">${w.id} (score: ${w.score})</span>
        <pre style="margin-top: 4px; font-size: 10px; color: #fda4af;">${escapeHtml(w.text)}</pre>
      </div>
    `;
  });
  baselineCard.innerHTML = baselineHtml;

  // 4. Update Constrained Prompt
  promptOutput.textContent = data.constructed_prompt;
}

async function runCompiler() {
  compileRunBtn.disabled = true;
  compileRunBtn.innerHTML = `<span>Compiling...</span>`;
  terminalOutput.textContent = "Compiling with opensource COBOL 4J Docker container...\n";

  try {
    const res = await fetch("/api/compile-and-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: state.activeFilename,
        source_code: codeEditor.value
      })
    });
    const result = await res.json();
    
    // Switch to compiler tab
    document.querySelector('.right-tab[data-tab="compiler"]').click();

    const noticeEl = document.getElementById("persistedNotice");
    if (result.success) {
      terminalOutput.textContent = `[COMPILATION SUCCESSFUL]\n${result.stdout}`;
      generatedJavaOutput.textContent = result.generated_java || "// No Java output produced";
      if (noticeEl) {
        const savedMsg = result.saved_files && result.saved_files.length > 0 
          ? `Persisted to disk: web_studio/generated_java/${result.saved_files.join(", ")}` 
          : "Persisted to project workspace";
        noticeEl.textContent = `✓ ${savedMsg}`;
        noticeEl.style.display = "block";
      }
    } else {
      terminalOutput.textContent = `[COMPILATION ERROR]\n${result.stderr || result.stdout}`;
      generatedJavaOutput.textContent = result.generated_java || "// Compilation failed";
      if (noticeEl) {
        noticeEl.style.display = "none";
      }
    }
  } catch (err) {
    terminalOutput.textContent = `[EXECUTION FAILED]: ${err.message}`;
  } finally {
    compileRunBtn.disabled = false;
    compileRunBtn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      Compile & Run
    `;
  }
}

// -------------------------------------------------------------
// Interactive SVG Graph Renderer (AST & Dependency Network)
// -------------------------------------------------------------
function renderGraph() {
  if (!state.parsedData) return;
  const svg = graphSvg;
  svg.innerHTML = `
    <rect class="bg-drag" width="100%" height="100%" fill="transparent"/>
    <defs>
      <marker id="arrow-calls" viewBox="0 -5 10 10" refX="28" refY="0" markerWidth="6" markerHeight="6" orient="auto">
        <path d="M0,-5L10,0L0,5" fill="#10b981"/>
      </marker>
      <marker id="arrow-depends" viewBox="0 -5 10 10" refX="28" refY="0" markerWidth="6" markerHeight="6" orient="auto">
        <path d="M0,-5L10,0L0,5" fill="#f59e0b"/>
      </marker>
      <marker id="arrow-ast" viewBox="0 -5 10 10" refX="15" refY="0" markerWidth="5" markerHeight="5" orient="auto">
        <path d="M0,-5L10,0L0,5" fill="#6366f1"/>
      </marker>
    </defs>
    <g id="graphGroup"></g>
  `;

  const group = document.getElementById("graphGroup");

  if (state.viewMode === "ast") {
    renderAstTree(group);
  } else {
    renderDependencyNetwork(group);
  }

  updateSvgTransform();
}

// Render Abstract Syntax Tree (Hierarchical Tree)
function renderAstTree(container) {
  const ast = state.parsedData.ast;
  const width = graphSvg.clientWidth || 900;
  const startX = width / 2;
  const startY = 60;

  // Flatten tree with calculated X, Y levels
  const nodes = [];
  const links = [];

  function layoutTree(node, level, leftBound, rightBound) {
    const x = (leftBound + rightBound) / 2;
    const y = startY + level * 85;
    nodes.push({ ...node, x, y, level });

    if (node.children && node.children.length > 0) {
      const childCount = node.children.length;
      const step = (rightBound - leftBound) / childCount;
      node.children.forEach((child, i) => {
        const cLeft = leftBound + i * step;
        const cRight = cLeft + step;
        layoutTree(child, level + 1, cLeft, cRight);
        links.push({ source: { x, y }, target: { x: (cLeft + cRight) / 2, y: startY + (level + 1) * 85 } });
      });
    }
  }

  layoutTree(ast, 0, 40, width - 40);

  // Render tree links
  links.forEach(l => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "line");
    path.setAttribute("x1", l.source.x);
    path.setAttribute("y1", l.source.y);
    path.setAttribute("x2", l.target.x);
    path.setAttribute("y2", l.target.y);
    path.setAttribute("stroke", "rgba(99, 102, 241, 0.35)");
    path.setAttribute("stroke-width", "1.5");
    container.appendChild(path);
  });

  // Render tree nodes
  nodes.forEach(n => {
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("transform", `translate(${n.x}, ${n.y})`);
    g.style.cursor = "pointer";

    let color = "#6366f1"; // default
    let radius = 18;
    if (n.type === "program") { color = "#a855f7"; radius = 24; }
    else if (n.type === "division") { color = "#38bdf8"; radius = 20; }
    else if (n.type === "paragraph_chunk") { color = "#10b981"; radius = 20; }
    else if (n.type === "data_field") { color = "#f59e0b"; radius = 14; }
    else if (n.type && n.type.startsWith("stmt_")) { color = "#475569"; radius = 10; }

    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("r", radius);
    circle.setAttribute("fill", color);
    circle.setAttribute("stroke", "#ffffff");
    circle.setAttribute("stroke-width", "1.5");
    circle.setAttribute("filter", "drop-shadow(0 2px 5px rgba(0,0,0,0.5))");
    g.appendChild(circle);

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("y", radius + 14);
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("fill", "#e2e8f0");
    text.setAttribute("font-size", n.type === "program" || n.type === "division" ? "12px" : "10px");
    text.setAttribute("font-family", "Inter, sans-serif");
    text.textContent = n.name.length > 25 ? n.name.substring(0, 23) + ".." : n.name;
    g.appendChild(text);

    g.addEventListener("click", (e) => {
      e.stopPropagation();
      inspectAstNode(n);
    });

    container.appendChild(g);
  });
}

// Render Structural Dependency Graph (Paragraph Chunks & Variables)
function renderDependencyNetwork(container) {
  const data = state.parsedData;
  const chunks = data.chunks;
  const variables = data.variables;
  const edges = data.edges;

  const width = graphSvg.clientWidth || 900;
  const height = graphSvg.clientHeight || 600;

  // Build node collection
  const nodesMap = {};
  const nodes = [];

  // 1. Chunk nodes (Paragraphs)
  chunks.forEach((c, idx) => {
    const angle = (idx / chunks.length) * Math.PI * 1.5 - Math.PI * 0.75;
    const nodeObj = {
      id: c.id,
      name: c.name,
      type: "chunk",
      x: width * 0.45 + Math.cos(angle) * 180,
      y: height * 0.45 + Math.sin(angle) * 140,
      meta: c
    };
    nodesMap[c.id] = nodeObj;
    nodes.push(nodeObj);
  });

  // 2. Variable / Symbol nodes
  variables.forEach((v, idx) => {
    const varId = `DATA::${v.name}`;
    const nodeObj = {
      id: varId,
      name: v.name,
      type: "variable",
      x: width * 0.75 + (idx % 2 === 0 ? 30 : -30),
      y: 90 + idx * 50,
      meta: v
    };
    nodesMap[varId] = nodeObj;
    nodes.push(nodeObj);
  });

  // Highlight check for Dual-Memory View
  const retrievedBundleIds = new Set();
  const vectorHitIds = new Set();
  if (state.viewMode === "dual" && state.retrievalResult) {
    state.retrievalResult.ast_retrieval.bundle.forEach(b => retrievedBundleIds.add(b.id));
    state.retrievalResult.ast_retrieval.vector_entry_points.forEach(id => vectorHitIds.add(id));
  }

  // Draw Edges
  edges.forEach(e => {
    const src = nodesMap[e.source];
    const tgt = nodesMap[e.target];
    if (src && tgt) {
      const isCalls = e.type === "CALLS";
      const edgeStroke = isCalls ? "#10b981" : "#f59e0b";
      const markerId = isCalls ? "url(#arrow-calls)" : "url(#arrow-depends)";

      const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
      
      // Calculate curved Bezier path
      const dx = tgt.x - src.x;
      const dy = tgt.y - src.y;
      const cx = (src.x + tgt.x) / 2 - dy * 0.15;
      const cy = (src.y + tgt.y) / 2 + dx * 0.15;
      const d = `M ${src.x} ${src.y} Q ${cx} ${cy} ${tgt.x} ${tgt.y}`;

      line.setAttribute("d", d);
      line.setAttribute("stroke", edgeStroke);
      line.setAttribute("stroke-width", isCalls ? "2.2" : "1.8");
      line.setAttribute("fill", "none");
      line.setAttribute("marker-end", markerId);
      line.setAttribute("opacity", "0.85");

      // Label on edge
      const labelText = document.createElementNS("http://www.w3.org/2000/svg", "text");
      labelText.setAttribute("x", cx);
      labelText.setAttribute("y", cy);
      labelText.setAttribute("fill", edgeStroke);
      labelText.setAttribute("font-size", "10px");
      labelText.setAttribute("font-family", "JetBrains Mono, monospace");
      labelText.setAttribute("text-anchor", "middle");
      labelText.textContent = e.type;

      container.appendChild(line);
      container.appendChild(labelText);
    }
  });

  // Draw Nodes
  nodes.forEach(n => {
    const isChunk = n.type === "chunk";
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("transform", `translate(${n.x}, ${n.y})`);
    g.style.cursor = "pointer";

    // Dual memory highlights
    let isRetrieved = retrievedBundleIds.has(n.id);
    let isVectorHit = vectorHitIds.has(n.id);

    const radius = isChunk ? 26 : 18;
    let fillColor = isChunk ? "#10b981" : "#f59e0b";
    let strokeColor = "#ffffff";
    let strokeWidth = 2;

    if (state.viewMode === "dual") {
      if (isVectorHit) {
        fillColor = "#38bdf8";
        strokeColor = "#ffffff";
        strokeWidth = 3.5;
      } else if (isRetrieved) {
        fillColor = isChunk ? "#10b981" : "#f59e0b";
        strokeColor = "#facc15";
        strokeWidth = 3;
      } else {
        fillColor = "#334155";
        strokeColor = "rgba(255,255,255,0.2)";
        strokeWidth = 1;
      }
    }

    // Outer glow for retrieved items
    if (isVectorHit || isRetrieved) {
      const glow = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      glow.setAttribute("r", radius + 6);
      glow.setAttribute("fill", "none");
      glow.setAttribute("stroke", isVectorHit ? "rgba(56, 189, 248, 0.4)" : "rgba(250, 204, 21, 0.4)");
      glow.setAttribute("stroke-width", "4");
      g.appendChild(glow);
    }

    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("r", radius);
    circle.setAttribute("fill", fillColor);
    circle.setAttribute("stroke", strokeColor);
    circle.setAttribute("stroke-width", strokeWidth);
    circle.setAttribute("filter", "drop-shadow(0 4px 8px rgba(0,0,0,0.4))");
    g.appendChild(circle);

    // Node icon / short label
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("dy", "4");
    text.setAttribute("fill", "#ffffff");
    text.setAttribute("font-size", isChunk ? "11px" : "9.5px");
    text.setAttribute("font-weight", "600");
    text.setAttribute("font-family", "Inter, sans-serif");
    text.textContent = isChunk ? "PAR" : "VAR";
    g.appendChild(text);

    // Node Name underneath
    const nameText = document.createElementNS("http://www.w3.org/2000/svg", "text");
    nameText.setAttribute("text-anchor", "middle");
    nameText.setAttribute("y", radius + 15);
    nameText.setAttribute("fill", "#f8fafc");
    nameText.setAttribute("font-size", "11px");
    nameText.setAttribute("font-family", "JetBrains Mono, monospace");
    nameText.textContent = n.name;
    g.appendChild(nameText);

    g.addEventListener("click", (e) => {
      e.stopPropagation();
      inspectDependencyNode(n);
    });

    container.appendChild(g);
  });
}

// Node inspectors
function inspectAstNode(node) {
  let details = `AST Node: ${node.name}\nType: ${node.type}\n`;
  if (node.start_line) details += `Line Range: L${node.start_line} - L${node.end_line}\n`;
  if (node.children) details += `Children: ${node.children.length} sub-nodes\n`;
  terminalOutput.textContent = details;
}

function inspectDependencyNode(node) {
  let details = `Node: ${node.name}\nID: ${node.id}\nType: ${node.type.toUpperCase()}\n\n`;
  if (node.type === "chunk" && node.meta) {
    details += `Source Code:\n${node.meta.source}\n`;
  } else if (node.type === "variable" && node.meta) {
    details += `Variable Declaration:\n${node.meta.raw}\nLevel: ${node.meta.level}\nPicture: ${node.meta.pic || 'N/A'}\nInitial Value: ${node.meta.value || 'N/A'}\n`;
  }
  terminalOutput.textContent = details;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
