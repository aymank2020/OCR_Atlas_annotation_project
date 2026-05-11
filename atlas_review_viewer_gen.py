"""
Generate an interactive HTML viewer for episode re-audit results.

Input:
  - episodes_review_index.json (from atlas_review_builder.py)

Output:
  - atlas_review_viewer.html (single self-contained page with embedded data)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_html(data: Dict[str, Any], title: str) -> str:
    data_json = json.dumps(data, ensure_ascii=False)
    title_esc = title.replace("<", "&lt;").replace(">", "&gt;")
    build_nonce = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title_esc}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #f1f5f9;
      --panel: #ffffff;
      --panel2: #f8fafc;
      --border: #e2e8f0;
      --text: #1e293b;
      --muted: #64748b;
      --accent: #4f46e5;
      --accent-light: #e0e7ff;
      --ok: #10b981;
      --warn: #f59e0b;
      --bad: #ef4444;
      --unknown: #94a3b8;
      --blue: #3b82f6;
      --shadow-sm: 0 1px 3px rgba(0,0,0,.06);
      --shadow-md: 0 4px 12px rgba(0,0,0,.08);
      --radius: 12px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 24px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      box-shadow: var(--shadow-sm);
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    .title {{
      font-size: 17px;
      font-weight: 700;
      color: var(--text);
    }}
    .title small {{
      color: var(--muted);
      font-weight: 500;
      margin-left: 10px;
      font-size: 12px;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 340px 1fr;
      gap: 16px;
      padding: 16px;
      min-height: calc(100vh - 56px);
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow-sm);
      transition: box-shadow .2s;
    }}
    .card:hover {{
      box-shadow: var(--shadow-md);
    }}
    .left {{
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .controls {{
      padding: 14px;
      border-bottom: 1px solid var(--border);
      display: grid;
      gap: 10px;
      background: var(--panel2);
      border-radius: var(--radius) var(--radius) 0 0;
    }}
    input, select {{
      width: 100%;
      padding: 9px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      font-family: inherit;
      font-size: 13px;
      transition: border-color .15s, box-shadow .15s;
    }}
    input:focus, select:focus {{
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-light);
    }}
    .episode-select {{
      width: 100%;
      min-height: 44px;
      font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
      font-size: 12px;
    }}
    .meta {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 12px;
      color: var(--muted);
      gap: 8px;
    }}
    .badge {{
      padding: 3px 10px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
      border: 1px solid transparent;
    }}
    .main {{
      padding: 16px;
      display: grid;
      gap: 14px;
      align-content: start;
    }}
    .section {{
      padding: 14px;
    }}
    .section h3 {{
      margin: 0 0 12px 0;
      font-size: 15px;
      font-weight: 600;
      color: var(--accent);
    }}
    .grid2 {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }}
    .grid3 {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .grid4 {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .labelbox {{
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px;
      background: var(--panel);
      box-shadow: var(--shadow-sm);
      transition: box-shadow .2s, transform .15s;
    }}
    .labelbox:hover {{
      box-shadow: var(--shadow-md);
      transform: translateY(-1px);
    }}
    .labels-row .labelbox {{
      display: flex;
      flex-direction: column;
      min-height: 460px;
    }}
    .labels-row pre {{
      flex: 1;
    }}
    .equal-row .labelbox {{
      display: flex;
      flex-direction: column;
      min-height: 280px;
    }}
    .equal-row pre {{
      flex: 1;
      max-height: none;
    }}
    .labelbox .tt {{
      margin: 0 0 10px 0;
      font-weight: 600;
      font-size: 13px;
      color: var(--accent);
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }}
    .timeline {{
      display: grid;
      gap: 6px;
      margin-bottom: 10px;
      max-height: 220px;
      overflow: auto;
      padding-right: 4px;
    }}
    .segrow {{
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel2);
      padding: 6px;
      display: grid;
      gap: 4px;
      transition: background .15s;
    }}
    .segrow:hover {{ background: var(--accent-light); }}
    .segbtn {{
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel);
      color: var(--text);
      padding: 6px 10px;
      font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
      font-size: 12px;
      cursor: pointer;
      transition: background .15s, border-color .15s;
    }}
    .segbtn:hover {{ background: var(--accent-light); border-color: var(--accent); }}
    .seglabel {{
      font-size: 12px;
      color: var(--text);
      line-height: 1.45;
      word-break: break-word;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
      font-size: 12px;
      line-height: 1.6;
      color: var(--text);
      max-height: 300px;
      overflow: auto;
      background: var(--panel2);
      padding: 10px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }}
    video {{
      width: 100%;
      max-height: 320px;
      border-radius: var(--radius);
      background: #000;
      border: 1px solid var(--border);
      box-shadow: var(--shadow-sm);
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
      transition: color .15s;
    }}
    a:hover {{ text-decoration: underline; color: #4338ca; }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 14px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      transition: all .15s;
      font-family: inherit;
    }}
    .btn:hover {{
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
      box-shadow: var(--shadow-sm);
    }}
    .stats {{
      font-size: 12px;
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .empty {{
      color: var(--muted);
      font-size: 13px;
      padding: 16px;
      border: 1px dashed var(--border);
      border-radius: var(--radius);
      background: var(--panel2);
      text-align: center;
    }}
    .warn {{
      color: var(--warn);
      font-size: 12px;
      margin-top: 8px;
    }}
    textarea {{
      width: 100%;
      min-height: 140px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--panel);
      color: var(--text);
      padding: 12px;
      resize: vertical;
      font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;
      font-size: 12px;
      line-height: 1.6;
      transition: border-color .15s, box-shadow .15s;
    }}
    textarea:focus {{
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-light);
    }}
    .score-badge {{
      padding: 4px 14px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      border: 1px solid transparent;
      display: inline-flex;
      align-items: center;
      min-width: 110px;
      justify-content: center;
    }}
    .score-green {{ background: rgba(16,185,129,.12); color: #059669; border-color: rgba(16,185,129,.3); }}
    .score-red {{ background: rgba(239,68,68,.1); color: #dc2626; border-color: rgba(239,68,68,.25); }}
    .score-yellow {{ background: rgba(245,158,11,.12); color: #d97706; border-color: rgba(245,158,11,.3); }}
    .score-gray {{ background: var(--panel2); color: var(--muted); border-color: var(--border); }}
    .compare-summary {{
      gap: 10px;
      margin-bottom: 12px;
      padding: 10px;
      background: var(--panel2);
      border-radius: 8px;
      border: 1px solid var(--border);
    }}
    .compare-summary b {{
      color: var(--text);
    }}
    @media (max-width: 1000px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .grid2 {{ grid-template-columns: 1fr; }}
      .grid3 {{ grid-template-columns: 1fr; }}
      .grid4 {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="top">
    <div class="title">
      Atlas Episode Review Viewer | عارض مراجعة الحلقات
      <small id="metaInfo"></small>
    </div>
    <div class="stats" id="topStats"></div>
  </div>

  <div class="layout">
    <div class="card left">
      <div class="controls">
        <input id="search" placeholder="Search episode id | ابحث برقم الحلقة" />
        <select id="statusFilter"></select>
        <select id="episodeSelect" class="episode-select"></select>
      </div>
    </div>

    <div class="card main">
      <div class="section">
        <h3>Episode | الحلقة</h3>
        <div id="episodeInfo" class="empty">Select an episode from the left list | اختر حلقة من القائمة</div>
      </div>

      <div class="section">
        <h3>Video | الفيديو</h3>
        <video id="videoPlayer" controls preload="metadata"></video>
        <div id="videoNote" class="warn"></div>
      </div>

      <div class="section grid4 labels-row">
        <div class="labelbox">
          <div class="tt">Gemini Chat (Timed) | إجابة جيمناي شات بالتوقيت</div>
          <div id="chatTimeline" class="timeline"></div>
          <pre id="chatBox">-</pre>
        </div>
        <div class="labelbox">
          <div class="tt">Vertex Chat | إجابة شات Vertex</div>
          <div id="vertexChatTimeline" class="timeline"></div>
          <pre id="vertexChatBox">-</pre>
        </div>
        <div class="labelbox">
          <div class="tt">Tier2 (Before) | قبل التعديل</div>
          <div id="tier2Timeline" class="timeline"></div>
          <pre id="tier2Box">-</pre>
        </div>
        <div class="labelbox">
          <div class="tt">Tier3 (After) | بعد التعديل</div>
          <div id="tier3Timeline" class="timeline"></div>
          <pre id="tier3Box">-</pre>
        </div>
      </div>

      <div class="section grid2 equal-row">
        <div class="labelbox">
          <div class="tt">Validation | التحقق</div>
          <pre id="validationBox">-</pre>
        </div>
        <div class="labelbox">
          <div class="tt">Disputes (sample) | النزاعات (عينة)</div>
          <pre id="disputesBox">-</pre>
        </div>
      </div>

      <div class="section">
        <h3>Comparison Result | نتيجة المقارنة</h3>
        <div class="labelbox">
          <div id="tripletCompareSummary" class="stats compare-summary"></div>
          <div class="stats" style="margin-bottom:8px">
            <span><a id="openGeminiChatLink" href="https://gemini.google.com/app/b3006ba9f325b55c" target="_blank">Open Gemini Chat</a></span>
            <span><button id="geminiEvalSaveBtn" class="btn" type="button">Save Evaluate</button></span>
            <span><button id="geminiEvalClearBtn" class="btn" type="button">Clear</button></span>
            <span><button id="geminiEvalExportBtn" class="btn" type="button">Export JSON</button></span>
            <span><button id="geminiEvalImportBtn" class="btn" type="button">Import JSON</button></span>
            <input id="geminiEvalImportFile" type="file" accept=".json" style="display:none" />
          </div>
          <textarea id="geminiEvalText" placeholder="Paste Gemini chat evaluation here | الصق نتيجة Gemini هنا"></textarea>
          <div class="stats" style="margin-top:8px">
            <span>
              <input id="geminiEvalScoreInput" type="number" min="0" max="100" step="1" style="width:90px" placeholder="Score %" />
            </span>
            <span><button id="geminiEvalAutoScoreBtn" class="btn" type="button">Auto Score</button></span>
            <span id="geminiEvalScoreBadge" class="score-badge score-gray">N/A</span>
            <span id="geminiEvalSavedAt" style="color:var(--muted)"></span>
          </div>
          <pre id="tripletCompareBox">-</pre>
        </div>
      </div>
    </div>
  </div>

  <script>
    const DATA = {data_json};
    const VIEWER_BUILD_NONCE = "{build_nonce}";
    function withCacheBust(url) {{
      const s = String(url || "");
      if (!s) return s;
      return `${{s}}${{s.includes("?") ? "&" : "?"}}v=${{encodeURIComponent(VIEWER_BUILD_NONCE)}}`;
    }}
    const episodes = Array.isArray(DATA.episodes) ? DATA.episodes : [];
    const episodesById = {{}};
    episodes.forEach((ep) => {{
      const key = String((ep && ep.episode_id) || "").trim().toLowerCase();
      if (key) episodesById[key] = ep;
    }});
    const statusCounts = episodes.reduce((acc, e) => {{
      const s = (e.review_status || "unknown");
      acc[s] = (acc[s] || 0) + 1;
      return acc;
    }}, {{}});

    const COLORS = {{
      submitted: ["#1d2e27", "#7aad8f"],
      disputed: ["#322224", "#c98f8f"],
      policy_fail: ["#332d21", "#d2bb86"],
      error: ["#2f2741", "#b69ad4"],
      labeled_not_submitted: ["#233046", "#95aecd"],
      unknown: ["#243042", "#98a4b8"]
    }};

    const metaInfo = document.getElementById("metaInfo");
    const topStats = document.getElementById("topStats");
    const episodeSelectEl = document.getElementById("episodeSelect");
    const searchEl = document.getElementById("search");
    const statusEl = document.getElementById("statusFilter");
    const episodeInfo = document.getElementById("episodeInfo");
    const video = document.getElementById("videoPlayer");
    const videoNote = document.getElementById("videoNote");
    const tier2Box = document.getElementById("tier2Box");
    const tier3Box = document.getElementById("tier3Box");
    const tier2Timeline = document.getElementById("tier2Timeline");
    const tier3Timeline = document.getElementById("tier3Timeline");
    const chatBox = document.getElementById("chatBox");
    const chatTimeline = document.getElementById("chatTimeline");
    const vertexChatBox = document.getElementById("vertexChatBox");
    const vertexChatTimeline = document.getElementById("vertexChatTimeline");
    const validationBox = document.getElementById("validationBox");
    const disputesBox = document.getElementById("disputesBox");
    const tripletCompareSummary = document.getElementById("tripletCompareSummary");
    const tripletCompareBox = document.getElementById("tripletCompareBox");
    const geminiEvalText = document.getElementById("geminiEvalText");
    const geminiEvalScoreInput = document.getElementById("geminiEvalScoreInput");
    const geminiEvalScoreBadge = document.getElementById("geminiEvalScoreBadge");
    const geminiEvalSavedAt = document.getElementById("geminiEvalSavedAt");
    const geminiEvalSaveBtn = document.getElementById("geminiEvalSaveBtn");
    const geminiEvalClearBtn = document.getElementById("geminiEvalClearBtn");
    const geminiEvalAutoScoreBtn = document.getElementById("geminiEvalAutoScoreBtn");
    const geminiEvalExportBtn = document.getElementById("geminiEvalExportBtn");
    const geminiEvalImportBtn = document.getElementById("geminiEvalImportBtn");
    const geminiEvalImportFile = document.getElementById("geminiEvalImportFile");
    const openGeminiChatLink = document.getElementById("openGeminiChatLink");
    const GEMINI_CHAT_URL = "https://gemini.google.com/app/b3006ba9f325b55c";
    let currentEpisodeId = "";
    let evalStore = {{}};
    let tripletCompareStore = {{}};
    let tripletDetailStore = {{}};
    let textRefCache = {{}};
    let segStopAt = null;

    function loadLocalEvalStore() {{
      try {{
        const raw = localStorage.getItem("atlas_gemini_eval_store_v1");
        if (!raw) return {{}};
        const obj = JSON.parse(raw);
        return obj && typeof obj === "object" ? obj : {{}};
      }} catch (_) {{
        return {{}};
      }}
    }}

    function saveLocalEvalStore() {{
      try {{
        localStorage.setItem("atlas_gemini_eval_store_v1", JSON.stringify(evalStore));
      }} catch (_) {{}}
    }}

    function mergeEvalStores(base, incoming) {{
      const out = Object.assign({{}}, base || {{}});
      Object.entries(incoming || {{}}).forEach(([eid, rec]) => {{
        if (!rec || typeof rec !== "object") return;
        const oldRec = out[eid];
        if (!oldRec) {{
          out[eid] = rec;
          return;
        }}
        const oldTs = String(oldRec.updated_at_utc || "");
        const newTs = String(rec.updated_at_utc || "");
        out[eid] = newTs >= oldTs ? rec : oldRec;
      }});
      return out;
    }}

    async function loadExternalEvalStore() {{
      try {{
        const res = await fetch(withCacheBust("gemini_chat_evaluations.json"), {{ cache: "no-store" }});
        if (!res.ok) return;
        const data = await res.json();
        let incoming = {{}};
        if (Array.isArray(data)) {{
          data.forEach((rec) => {{
            if (!rec || typeof rec !== "object") return;
            const eid = String(rec.episode_id || "");
            if (!eid) return;
            incoming[eid] = rec;
          }});
        }} else if (data && typeof data === "object") {{
          if (Array.isArray(data.evaluations)) {{
            data.evaluations.forEach((rec) => {{
              if (!rec || typeof rec !== "object") return;
              const eid = String(rec.episode_id || "");
              if (!eid) return;
              incoming[eid] = rec;
            }});
          }} else if (data.evaluations && typeof data.evaluations === "object") {{
            incoming = data.evaluations;
          }} else {{
            Object.entries(data).forEach(([eid, rec]) => {{
              if (!rec || typeof rec !== "object") return;
              if (!("text" in rec) && !("score_pct" in rec) && !("episode_id" in rec)) return;
              incoming[String(eid)] = rec;
            }});
          }}
        }}
        evalStore = mergeEvalStores(evalStore, incoming);
        saveLocalEvalStore();
        if (currentEpisodeId) renderEvalForEpisode(currentEpisodeId);
      }} catch (_) {{
        // optional file
      }}
    }}

    async function loadTripletCompareStore() {{
      try {{
        const res = await fetch(withCacheBust("triplet_compare_results.jsonl"), {{ cache: "no-store" }});
        if (!res.ok) return;
        const raw = await res.text();
        const map = {{}};
        raw.split(/\\r?\\n/).forEach((line) => {{
          const txt = String(line || "").trim();
          if (!txt) return;
          try {{
            const rec = JSON.parse(txt);
            const eid = String(rec.episode_id || "").trim();
            if (!eid) return;
            map[eid] = rec;
            map[eid.toLowerCase()] = rec;
          }} catch (_) {{}}
        }});
        tripletCompareStore = map;
        tripletDetailStore = {{}};
        textRefCache = {{}};
        if (currentEpisodeId) {{
          renderTripletCompareForEpisode(currentEpisodeId);
          renderChatForEpisode(currentEpisodeId);
          renderVertexChatForEpisode(currentEpisodeId);
        }}
      }} catch (_) {{
        // optional file
      }}
    }}

    function scoreToBadge(score) {{
      const n = Number(score);
      if (!Number.isFinite(n)) {{
        return {{ cls: "score-gray", txt: "N/A" }};
      }}
      const v = Math.max(0, Math.min(100, Math.round(n)));
      if (v >= 95) return {{ cls: "score-green", txt: `PASS ${{v}}%` }};
      return {{ cls: "score-red", txt: `FAIL ${{v}}%` }};
    }}

    function applyScoreBadge(score) {{
      const b = scoreToBadge(score);
      geminiEvalScoreBadge.className = `score-badge ${{b.cls}}`;
      geminiEvalScoreBadge.textContent = b.txt;
    }}

    function parseScoreFromText(text) {{
      const t = String(text || "");
      const m = t.match(/(?:score|confidence|accuracy|quality|percent|نسبة|تقييم)\\s*[:=\\-]?\\s*(\\d{{1,3}})\\s*%?/i) || t.match(/(\\d{{1,3}})\\s*%/);
      if (!m) return null;
      const n = Number(m[1]);
      if (!Number.isFinite(n)) return null;
      return Math.max(0, Math.min(100, Math.round(n)));
    }}

    function renderEvalForEpisode(eid) {{
      const rec = evalStore[eid] || {{}};
      geminiEvalText.value = String(rec.text || "");
      if (rec.score_pct === null || rec.score_pct === undefined || rec.score_pct === "") {{
        geminiEvalScoreInput.value = "";
      }} else {{
        geminiEvalScoreInput.value = String(rec.score_pct);
      }}
      applyScoreBadge(rec.score_pct);
      geminiEvalSavedAt.textContent = rec.updated_at_utc ? `saved: ${{rec.updated_at_utc}}` : "";
      renderChatForEpisode(eid);
      renderVertexChatForEpisode(eid);
    }}

    async function renderChatForEpisode(eid) {{
      const safeEid = String(eid || "");
      if (!safeEid || safeEid === "__none__") {{
        chatBox.textContent = "-";
        renderTimeline(chatTimeline, []);
        return;
      }}
      chatBox.textContent = "Loading timed chat labels...";
      renderTimeline(chatTimeline, []);

      const chatRaw = await resolveChatTimedText(safeEid);
      if (safeEid !== currentEpisodeId) return;
      if (!chatRaw) {{
        const why = buildMissingLabelReason(safeEid, "chat");
        chatBox.textContent = why ? `(missing timed labels)\n${{why}}` : "(missing timed labels)";
        renderTimeline(chatTimeline, []);
        return;
      }}
      const segs = parseSegments(chatRaw);
      if (!segs.length) {{
        chatBox.textContent = `${{chatRaw}}\n\n(no parsed timestamps)`;
        renderTimeline(chatTimeline, []);
        return;
      }}
      chatBox.textContent = chatRaw;
      renderTimeline(chatTimeline, segs);
    }}

    async function renderVertexChatForEpisode(eid) {{
      const safeEid = String(eid || "");
      if (!safeEid || safeEid === "__none__") {{
        vertexChatBox.textContent = "-";
        renderTimeline(vertexChatTimeline, []);
        return;
      }}
      vertexChatBox.textContent = "Loading vertex chat labels...";
      renderTimeline(vertexChatTimeline, []);

      const vertexRaw = await resolveVertexChatText(safeEid);
      if (safeEid !== currentEpisodeId) return;
      if (!vertexRaw) {{
        const why = buildMissingLabelReason(safeEid, "vertex");
        vertexChatBox.textContent = why ? `(missing vertex chat labels)\n${{why}}` : "(missing vertex chat labels)";
        renderTimeline(vertexChatTimeline, []);
        return;
      }}
      const segs = parseSegments(vertexRaw);
      if (!segs.length) {{
        vertexChatBox.textContent = `${{vertexRaw}}\n\n(no parsed timestamps)`;
        renderTimeline(vertexChatTimeline, []);
        return;
      }}
      vertexChatBox.textContent = vertexRaw;
      renderTimeline(vertexChatTimeline, segs);
    }}

    async function renderTripletCompareForEpisode(eid) {{
      const safeEid = String(eid || "");
      let rec = getTripletRecord(safeEid);
      const detail = await getTripletDetailForEpisode(safeEid);
      if (!rec && detail && typeof detail === "object") {{
        const judgeTmp = detail.judge_result && typeof detail.judge_result === "object" ? detail.judge_result : {{}};
        const winnerTmp = String(judgeTmp.winner || "none");
        const scoreTmp = judgeTmp.scores && typeof judgeTmp.scores === "object" ? judgeTmp.scores[winnerTmp] : null;
        const j = (detail && detail.judge_result && typeof detail.judge_result === "object") ? detail.judge_result : {{}};
        rec = {{
          episode_id: safeEid,
          ok: Boolean(j.ok || j.validator_ok || (rec && rec.ok)),
          skipped: Boolean(j.skipped || (rec && rec.skipped)),
          reason: String(j.reason || (rec && rec.reason) || "loaded_from_detail"),
          winner: winnerTmp,
          score_pct: scoreTmp,
          submit_safe_solution: String(j.submit_safe_solution || (rec && rec.submit_safe_solution) || ""),
          result_path: (rec && rec.result_path) || `triplet_compare/triplet_compare_${{safeEid.trim().toLowerCase()}}.json`,
        }};
      }}
      if (!rec) {{
        tripletCompareSummary.innerHTML = `<span>No triplet result loaded for this episode.</span>`;
        tripletCompareBox.textContent = "(missing)";
        return;
      }}
      if (safeEid !== currentEpisodeId) return;
      const judge = detail && typeof detail === "object" && detail.judge_result && typeof detail.judge_result === "object"
        ? detail.judge_result
        : null;

      const winner = String((judge && judge.winner) || rec.winner || "none");
      const scoreRaw = (judge && judge.scores && typeof judge.scores === "object")
        ? judge.scores[winner]
        : rec.score_pct;
      const score = scoreRaw === null || scoreRaw === undefined || scoreRaw === "" ? "n/a" : String(scoreRaw);
      const reason = String(
        (judge && (judge.best_reason_short || judge.final_recommendation)) ||
        rec.reason ||
        ""
      );
      const submitSafe = String((judge && judge.submit_safe_solution) || rec.submit_safe_solution || "n/a");
      const statusTxt = rec.ok ? "ok" : (rec.skipped ? "skipped" : "error");
      tripletCompareSummary.innerHTML = `
        <span><b>Status:</b> ${{statusTxt}}</span>
        <span><b>Winner:</b> ${{winner}}</span>
        <span><b>Score:</b> ${{score}}</span>
        <span><b>Submit Safe:</b> ${{submitSafe}}</span>
      `;
      if (judge) {{
        tripletCompareBox.textContent = JSON.stringify(judge, null, 2);
        return;
      }}
      const fallbackDetails = {{
        episode_id: rec.episode_id || eid,
        status: statusTxt,
        winner: winner,
        score_pct: rec.score_pct,
        submit_safe_solution: rec.submit_safe_solution,
        reason: reason,
        issues: rec.issues || null,
        result_path: rec.result_path || "",
      }};
      tripletCompareBox.textContent = JSON.stringify(fallbackDetails, null, 2);
    }}

    function saveCurrentEval() {{
      if (!currentEpisodeId) return;
      const txt = String(geminiEvalText.value || "").trim();
      const manual = geminiEvalScoreInput.value === "" ? null : Number(geminiEvalScoreInput.value);
      const score = Number.isFinite(manual) ? Math.max(0, Math.min(100, Math.round(manual))) : parseScoreFromText(txt);
      const now = new Date().toISOString();
      evalStore[currentEpisodeId] = {{
        episode_id: currentEpisodeId,
        text: txt,
        score_pct: score,
        updated_at_utc: now,
        source: "viewer_manual",
      }};
      saveLocalEvalStore();
      renderEvalForEpisode(currentEpisodeId);
    }}

    function clearCurrentEval() {{
      if (!currentEpisodeId) return;
      delete evalStore[currentEpisodeId];
      saveLocalEvalStore();
      renderEvalForEpisode(currentEpisodeId);
    }}

    metaInfo.textContent = `generated: ${{DATA.generated_at_utc || "n/a"}}`;
    topStats.innerHTML = `
      <span>Total | الإجمالي: <b>${{episodes.length}}</b></span>
      <span>Statuses | الحالات: <b>${{Object.keys(statusCounts).length}}</b></span>
    `;

    function statusBadge(status) {{
      const s = status || "unknown";
      const c = COLORS[s] || COLORS.unknown;
      return `<span class="badge" style="background:${{c[0]}}; color:${{c[1]}}; border-color:${{c[1]}}33">${{s}}</span>`;
    }}

    function normalizePath(p) {{
      if (!p) return "";
      let s = String(p).replace(/\\\\/g, "/");
      if (/^https?:\\/\\//i.test(s)) return s;
      const low = s.toLowerCase();
      const i1 = low.lastIndexOf("/outputs/");
      if (i1 >= 0) s = s.slice(i1 + "/outputs/".length);
      const i2 = low.lastIndexOf("outputs/");
      if (i1 < 0 && i2 >= 0) s = s.slice(i2 + "outputs/".length);
      if (/^[a-zA-Z]:\\//.test(s)) return "";
      return encodeURI(s);
    }}

    function parseTimeToSec(v) {{
      if (typeof v === "number") return v;
      const s = String(v || "").trim();
      if (!s) return null;
      if (/^\\d+(\\.\\d+)?$/.test(s)) return Number(s);
      const parts = s.split(":").map((x) => Number(x));
      if (parts.some((x) => Number.isNaN(x))) return null;
      if (parts.length === 2) {{
        return parts[0] * 60 + parts[1];
      }}
      if (parts.length === 3) {{
        return parts[0] * 3600 + parts[1] * 60 + parts[2];
      }}
      return null;
    }}

    function secToStamp(sec) {{
      const s = Number(sec || 0);
      const m = Math.floor(s / 60);
      const rem = (s - m * 60).toFixed(1).padStart(4, "0");
      return `${{m}}:${{rem}}`;
    }}

    function toText(v) {{
      if (!v) return "(missing)";
      if (typeof v === "string") return v;
      if (Array.isArray(v)) {{
        return v.map((s) => {{
          if (typeof s === "object" && s) {{
            const a = s.start_sec ?? s.start ?? "";
            const b = s.end_sec ?? s.end ?? "";
            return `${{a}} -> ${{b}} | ${{s.label || ""}}`;
          }}
          return String(s);
        }}).join("\\n");
      }}
      if (typeof v === "object") {{
        if (Array.isArray(v.segments)) {{
          return toText(v.segments);
        }}
        return JSON.stringify(v, null, 2);
      }}
      return String(v);
    }}

    function getEpisodeById(eid) {{
      const key = String(eid || "").trim().toLowerCase();
      return episodesById[key] || null;
    }}

    function getTripletRecord(eid) {{
      const raw = String(eid || "").trim();
      if (!raw) return null;
      return tripletCompareStore[raw] || tripletCompareStore[raw.toLowerCase()] || null;
    }}

    function collectTripletResultRefs(eid) {{
      const key = String(eid || "").trim().toLowerCase();
      if (!key) return [];
      const refs = [];
      const pushIf = (v) => {{
        const p = normalizePath(v);
        if (p) refs.push(p);
      }};
      pushIf(`triplet_compare/triplet_compare_${{key}}.json`);
      const ep = getEpisodeById(key);
      if (!ep) return refs;
      pushIf(ep.triplet_result_path);
      const files = Array.isArray(ep.related_files) ? ep.related_files : [];
      files.forEach((fp) => {{
        const raw = String(fp || "");
        if (!raw) return;
        const base = raw.replace(/\\\\/g, "/").split("/").pop().toLowerCase();
        if (base === `triplet_compare_${{key}}.json`) pushIf(raw);
      }});
      return refs;
    }}

    function collectRelatedRefs(eid, kind) {{
      const ep = getEpisodeById(eid);
      if (!ep) return [];
      const key = String(eid || "").trim().toLowerCase();
      const refs = [];
      const pushIf = (v) => {{
        const p = normalizePath(v);
        if (p) refs.push(p);
      }};

      if (kind === "chat") {{
        pushIf(ep.chat_path);
      }} else if (kind === "vertex") {{
        pushIf(ep.vertex_chat_path);
      }}

      const files = Array.isArray(ep.related_files) ? ep.related_files : [];
      files.forEach((fp) => {{
        const raw = String(fp || "");
        if (!raw) return;
        const rawLow = raw.replace(/\\\\/g, "/").toLowerCase();
        const base = raw.replace(/\\\\/g, "/").split("/").pop().toLowerCase();
        if (!base.includes(key)) return;
        if (kind === "chat") {{
          if (
            base === `text_${{key}}_chat.txt` ||
            base === `labels_${{key}}_chat.json`
          ) {{
            pushIf(raw);
          }}
          if (base === `labels_${{key}}.json` && rawLow.includes("/chat_reviews/")) {{
            pushIf(raw);
          }}
          return;
        }}
        if (
          base === `text_${{key}}_vertex_chat.txt` ||
          base === `labels_${{key}}_vertex_chat.json` ||
          (base.includes("vertex_chat") && base.includes(key))
        ) {{
          pushIf(raw);
        }}
      }});
      return refs;
    }}

    function buildMissingLabelReason(eid, kind) {{
      const key = String(eid || "").trim().toLowerCase();
      if (!key) return "";
      const rec = getTripletRecord(key);
      if (!rec || typeof rec !== "object") return "";
      const reason = String(rec.reason || "").trim();
      if (!reason) return "";
      const low = reason.toLowerCase();
      if (kind === "chat" && low.includes("chat_path") && !low.includes("vertex_chat_path")) {{
        return `triplet: ${{reason}}`;
      }}
      if (kind === "vertex" && low.includes("vertex_chat_path")) return `triplet: ${{reason}}`;
      if (!rec.ok || rec.skipped) return `triplet: ${{reason}}`;
      return "";
    }}

    function buildChatPrompt(ep) {{
      const tier2Raw = ep.tier2_text || ep.tier2;
      const tier3Raw = ep.tier3_text || ep.tier3;
      const validation = ep.validation || {{}};
      const disputes = Array.isArray(ep.disputes) ? ep.disputes : [];

      const validationSummary = {{
        ok: validation.ok,
        episode_errors: validation.episode_errors || [],
        episode_warnings: validation.episode_warnings || [],
        major_fail_triggers: validation.major_fail_triggers || [],
        device_class_conflicts: validation.device_class_conflicts || [],
      }};

      return [
        "I need a strict Atlas Tier-4 audit for this episode.",
        "",
        `Episode ID: ${{ep.episode_id || ""}}`,
        `Atlas URL: ${{ep.atlas_url || ep.open_url || ""}}`,
        `Current status: ${{ep.review_status || "unknown"}}`,
        "",
        "[Tier2 - before AI update]",
        toText(tier2Raw),
        "",
        "[Tier3 - after AI update]",
        toText(tier3Raw),
        "",
        "[Validator summary]",
        JSON.stringify(validationSummary, null, 2),
        "",
        "[Disputes summary]",
        `Count: ${{disputes.length}}`,
        "Sample:",
        JSON.stringify(disputes.slice(0, 3), null, 2),
        "",
        "Please evaluate:",
        "1) Which is better: Tier2 or Tier3?",
        "2) Is Tier3 submit-safe according to Atlas policy?",
        "3) List exact segment-level issues with rule names.",
        "4) Provide corrected labels for failing segments.",
        "5) Final verdict: PASS / FAIL with confidence.",
        "",
        "مهم: اكتب الإجابة النهائية بالكامل باللغة العربية بشكل واضح ومباشر.",
      ].join("\\n");
    }}

    function buildAiInputBundle(ep) {{
      const eid = String(ep.episode_id || "");
      const evalRec = evalStore[eid] || null;
      return {{
        schema_version: "atlas_ai_input_bundle_v1",
        generated_at_utc: new Date().toISOString(),
        source: "atlas_review_viewer",
        episode: {{
          episode_id: eid,
          review_status: ep.review_status || "unknown",
          atlas_url: ep.atlas_url || ep.open_url || "",
          task_url: ep.task_url || "",
          feedback_url: ep.feedback_url || "",
          disputes_url: ep.disputes_url || "",
          total_cost_usd: Number(ep.total_cost_usd || 0),
          tier2: ep.tier2_text || ep.tier2 || null,
          tier3: ep.tier3_text || ep.tier3 || null,
          validation: ep.validation || null,
          disputes: Array.isArray(ep.disputes) ? ep.disputes : [],
        }},
        ai_evaluate: evalRec,
      }};
    }}

    function buildAiInputPrompt(ep) {{
      const bundle = buildAiInputBundle(ep);
      return [
        "Use this AI input bundle for strict Atlas Tier-4 audit.",
        "اعتمد JSON التالي كمدخل مراجعة شامل للحلقة.",
        "",
        "[AI_INPUT_BUNDLE_JSON]",
        JSON.stringify(bundle, null, 2),
        "",
        "Required output:",
        "1) Compare Tier2 vs Tier3 vs Gemini Chat (Timed) vs Vertex Chat",
        "2) choose the safest winner",
        "3) exact segment-level issues with rule names",
        "4) corrected labels for failing segments",
        "5) final PASS/FAIL + confidence",
        "",
        "اكتب الإجابة النهائية بالعربية وبشكل مباشر.",
      ].join("\\n");
    }}

    function parseSegments(v) {{
      const out = [];
      if (!v) return out;

      if (Array.isArray(v)) {{
        v.forEach((s) => {{
          if (!s || typeof s !== "object") return;
          const a = s.start_sec ?? s.start;
          const b = s.end_sec ?? s.end;
          const aSec = parseTimeToSec(a);
          const bSec = parseTimeToSec(b);
          if (aSec == null || bSec == null) return;
          out.push({{
            start_sec: aSec,
            end_sec: bSec,
            start_text: typeof a === "number" ? secToStamp(aSec) : String(a),
            end_text: typeof b === "number" ? secToStamp(bSec) : String(b),
            label: String(s.label || "").trim(),
          }});
        }});
        return out;
      }}

      if (typeof v === "object" && Array.isArray(v.segments)) {{
        return parseSegments(v.segments);
      }}

      if (typeof v === "string") {{
        const rawText = String(v || "").trim();
        if (rawText) {{
          const unwrapped = rawText.replace(/^```(?:json|txt)?\\s*/i, "").replace(/```$/i, "").trim();
          const jsonCandidates = [unwrapped];
          const firstObj = unwrapped.indexOf("{{");
          const lastObj = unwrapped.lastIndexOf("}}");
          if (firstObj >= 0 && lastObj > firstObj) {{
            jsonCandidates.push(unwrapped.slice(firstObj, lastObj + 1));
          }}
          const firstArr = unwrapped.indexOf("[");
          const lastArr = unwrapped.lastIndexOf("]");
          if (firstArr >= 0 && lastArr > firstArr) {{
            jsonCandidates.push(unwrapped.slice(firstArr, lastArr + 1));
          }}
          for (const c of jsonCandidates) {{
            const t = String(c || "").trim();
            if (!t) continue;
            try {{
              const parsed = JSON.parse(t);
              const segs = parseSegments(parsed);
              if (Array.isArray(segs) && segs.length) return segs;
            }} catch (_) {{}}
          }}
        }}
      }}

      const lines = String(v).split(/\\r?\\n/).map((x) => x.trim()).filter(Boolean);
      lines.forEach((line) => {{
        const tabParts = line.split(/\\t+/).map((x) => x.trim()).filter(Boolean);
        if (tabParts.length >= 3) {{
          // Typical atlas text dump:
          // 1\t0.0\t3.3\tlabel
          // or 0.0\t3.3\tlabel
          const aRaw = tabParts.length >= 4 ? tabParts[1] : tabParts[0];
          const bRaw = tabParts.length >= 4 ? tabParts[2] : tabParts[1];
          const labelRaw = tabParts.length >= 4 ? tabParts.slice(3).join(" ") : tabParts.slice(2).join(" ");
          const aSec = parseTimeToSec(aRaw);
          const bSec = parseTimeToSec(bRaw);
          if (aSec != null && bSec != null) {{
            out.push({{
              start_sec: aSec,
              end_sec: bSec,
              start_text: secToStamp(aSec),
              end_text: secToStamp(bSec),
              label: String(labelRaw || "").trim(),
            }});
            return;
          }}
        }}

        // Flexible pattern:
        // 1 | 0.0 | 4.2 | label
        // 0.0 4.2 label
        const flat = line.replace(/\\s*\\|\\s*/g, " ").replace(/\\s+/g, " ").trim();
        const m = flat.match(/^(?:\\d+\\s+)?(\\d+(?:\\.\\d+)?)\\s+(\\d+(?:\\.\\d+)?)\\s+(.+)$/);
        if (m) {{
          const aSec = parseTimeToSec(m[1]);
          const bSec = parseTimeToSec(m[2]);
          if (aSec != null && bSec != null) {{
            out.push({{
              start_sec: aSec,
              end_sec: bSec,
              start_text: secToStamp(aSec),
              end_text: secToStamp(bSec),
              label: String(m[3] || "").trim(),
            }});
            return;
          }}
        }}

        const matches = line.match(/\\d+:\\d+(?:\\.\\d+)?/g);
        if (!matches || matches.length < 2) return;
        const startText = matches[0];
        const endText = matches[1];
        const startSec = parseTimeToSec(startText);
        const endSec = parseTimeToSec(endText);
        if (startSec == null || endSec == null) return;

        const endIdx = line.indexOf(endText);
        let label = endIdx >= 0 ? line.slice(endIdx + endText.length).trim() : "";
        label = label.replace(/^[-–—>|#\\d\\.\\s]+/, "").trim();
        out.push({{
          start_sec: startSec,
          end_sec: endSec,
          start_text: startText,
          end_text: endText,
          label,
        }});
      }});
      return out;
    }}

    async function loadTextFromRef(ref) {{
      const key = normalizePath(ref);
      if (!key) return "";
      if (Object.prototype.hasOwnProperty.call(textRefCache, key)) {{
        return String(textRefCache[key] || "");
      }}
      try {{
        const res = await fetch(withCacheBust(key), {{ cache: "no-store" }});
        if (!res.ok) {{
          textRefCache[key] = "";
          return "";
        }}
        const raw = await res.text();
        let out = raw;
        if (key.toLowerCase().endsWith(".json")) {{
          try {{
            out = toText(JSON.parse(raw));
          }} catch (_) {{
            out = raw;
          }}
        }}
        textRefCache[key] = out;
        return out;
      }} catch (_) {{
        textRefCache[key] = "";
        return "";
      }}
    }}

    async function getTripletDetailForEpisode(eid) {{
      const key = String(eid || "").trim().toLowerCase();
      if (!key) return null;
      if (Object.prototype.hasOwnProperty.call(tripletDetailStore, key)) {{
        return tripletDetailStore[key];
      }}
      const row = getTripletRecord(key);
      const refs = [];
      if (row && typeof row === "object" && row.result_path) refs.push(row.result_path);
      refs.push(...collectTripletResultRefs(key));

      for (const ref of refs) {{
        const path = normalizePath(ref);
        if (!path) continue;
        try {{
          const res = await fetch(withCacheBust(path), {{ cache: "no-store" }});
          if (!res.ok) continue;
          const obj = await res.json();
          tripletDetailStore[key] = obj;
          return obj;
        }} catch (_) {{
          // try next candidate
        }}
      }}
      tripletDetailStore[key] = null;
      return null;
    }}

    async function resolveChatTimedText(eid) {{
      const key = String(eid || "");
      if (!key) return "";

      const detail = await getTripletDetailForEpisode(key);
      const rec = getTripletRecord(key);
      const refs = [];
      if (detail && typeof detail === "object" && detail.text_refs && typeof detail.text_refs === "object") {{
        const t = detail.text_refs;
        refs.push(t.resolved_chat_path, t.chat_path, t.labels_path);
      }}
      if (rec && typeof rec === "object") {{
        refs.push(rec.chat_path);
      }}
      refs.push(`chat_reviews/${{key}}/text_${{key}}_chat.txt`);
      refs.push(`chat_reviews/${{key}}/labels_${{key}}.json`);
      refs.push(...collectRelatedRefs(key, "chat"));

      for (const ref of refs) {{
        const txt = await loadTextFromRef(ref);
        if (!txt) continue;
        const segs = parseSegments(txt);
        if (segs.length > 0) return txt;
      }}
      return "";
    }}

    async function resolveVertexChatText(eid) {{
      const key = String(eid || "");
      if (!key) return "";

      const detail = await getTripletDetailForEpisode(key);
      const rec = getTripletRecord(key);
      const refs = [];
      if (detail && typeof detail === "object" && detail.text_refs && typeof detail.text_refs === "object") {{
        const t = detail.text_refs;
        refs.push(t.resolved_vertex_chat_path, t.vertex_chat_path);
      }}
      if (rec && typeof rec === "object") {{
        refs.push(rec.vertex_chat_path);
      }}
      refs.push(`vertex_chat_reviews/${{key}}/text_${{key}}_vertex_chat.txt`);
      refs.push(`vertex_chat_reviews/${{key}}/labels_${{key}}_vertex_chat.json`);
      refs.push(...collectRelatedRefs(key, "vertex"));

      for (const ref of refs) {{
        const txt = await loadTextFromRef(ref);
        if (!txt) continue;
        const segs = parseSegments(txt);
        if (segs.length > 0) return txt;
      }}
      return "";
    }}

    function jumpToSegment(startSec, endSec) {{
      if (!Number.isFinite(startSec)) return;
      try {{
        video.currentTime = Math.max(0, startSec);
      }} catch (_) {{}}
      if (Number.isFinite(endSec) && endSec > startSec) {{
        segStopAt = endSec;
      }} else {{
        segStopAt = null;
      }}
      video.play().catch(() => {{}});
    }}

    function renderTimeline(container, segments) {{
      container.innerHTML = "";
      if (!segments.length) {{
        container.innerHTML = `<div class="empty">No parsed timestamps | لا توجد أزمنة قابلة للنقر</div>`;
        return;
      }}
      segments.forEach((s, i) => {{
        const row = document.createElement("div");
        row.className = "segrow";
        row.innerHTML = `
          <button class="segbtn" type="button">${{i + 1}}) ${{s.start_text}} → ${{s.end_text}}</button>
          <div class="seglabel">${{(s.label || "(no label)").replace(/</g, "&lt;").replace(/>/g, "&gt;")}}</div>
        `;
        const btn = row.querySelector(".segbtn");
        btn.addEventListener("click", () => jumpToSegment(s.start_sec, s.end_sec));
        container.appendChild(row);
      }});
    }}

    function clearEpisodeView(msg) {{
      const text = msg || "No episodes match filter | لا توجد حلقات مطابقة";
      episodeInfo.innerHTML = `<div class="empty">${{text}}</div>`;
      video.removeAttribute("src");
      video.load();
      videoNote.textContent = "";
      tier2Box.textContent = "-";
      tier3Box.textContent = "-";
      chatBox.textContent = "-";
      vertexChatBox.textContent = "-";
      validationBox.textContent = "-";
      disputesBox.textContent = "-";
      tripletCompareSummary.innerHTML = `<span>-</span>`;
      tripletCompareBox.textContent = "-";
      renderTimeline(tier2Timeline, []);
      renderTimeline(tier3Timeline, []);
      renderTimeline(chatTimeline, []);
      renderTimeline(vertexChatTimeline, []);
      renderEvalForEpisode("__none__");
    }}

    function getFilteredEpisodes() {{
      const q = (searchEl.value || "").trim().toLowerCase();
      const sf = statusEl.value;
      return episodes.filter((ep) => {{
        const okStatus = sf === "all" ? true : (ep.review_status || "unknown") === sf;
        const okSearch = !q ? true : String(ep.episode_id || "").toLowerCase().includes(q);
        return okStatus && okSearch;
      }});
    }}

    function renderEpisodeSelect() {{
      const filtered = getFilteredEpisodes();
      episodeSelectEl.innerHTML = "";
      if (!filtered.length) {{
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No episodes match filter | لا توجد حلقات مطابقة";
        episodeSelectEl.appendChild(opt);
        currentEpisodeId = "";
        clearEpisodeView();
        return;
      }}

      filtered.forEach((ep) => {{
        const eid = String(ep.episode_id || "unknown");
        const status = String(ep.review_status || "unknown");
        const disputes = Number(ep.disputes_count || 0);
        const opt = document.createElement("option");
        opt.value = eid;
        opt.textContent = `${{eid}} | ${{status}} | disputes:${{disputes}}`;
        episodeSelectEl.appendChild(opt);
      }});

      const hasCurrent = filtered.some((ep) => String(ep.episode_id || "") === currentEpisodeId);
      const nextId = hasCurrent ? currentEpisodeId : String(filtered[0].episode_id || "");
      episodeSelectEl.value = nextId;
      const nextEpisode = filtered.find((ep) => String(ep.episode_id || "") === nextId);
      if (nextEpisode) selectEpisode(nextEpisode);
    }}

    function selectEpisode(ep) {{
      const eid = ep.episode_id || "unknown";
      currentEpisodeId = String(eid);
      const status = ep.review_status || "unknown";
      const cost = Number(ep.total_cost_usd || 0).toFixed(6);
      const atlasUrl = ep.atlas_url || ep.open_url || "";
      const taskUrl = ep.task_url || "";
      const feedbackUrl = ep.feedback_url || "";
      const disputesUrl = ep.disputes_url || "";
      const chatPromptRel = `chat_reviews/${{eid}}/chat_prompt.txt`;
      const chatMetaRel = `chat_reviews/${{eid}}/episode_meta.json`;
      const hasVideo = Boolean(ep.video_path || ep.video_web_path);
      const src = normalizePath(ep.video_web_path || ep.video_path || "");

      episodeInfo.innerHTML = `
        <div class="stats">
          <span><b>ID:</b> ${{eid}}</span>
          <span><b>Status | الحالة:</b> ${{statusBadge(status)}}</span>
          <span><b>Cost | التكلفة:</b> $${{cost}}</span>
          <span><b>Disputes | النزاعات:</b> ${{ep.disputes_count || 0}}</span>
          <span><a href="${{atlasUrl}}" target="_blank">Open Current | فتح الحالي</a></span>
          <span><a href="${{taskUrl}}" target="_blank">Task</a></span>
          <span><a href="${{feedbackUrl}}" target="_blank">Feedback</a></span>
          <span><a href="${{disputesUrl}}" target="_blank">Disputes</a></span>
          <span><a href="${{chatPromptRel}}" target="_blank">Chat Prompt</a></span>
          <span><a href="${{chatMetaRel}}" target="_blank">Episode Meta</a></span>
          <span><button id="copyPromptBtn" class="btn" type="button">Copy Chat Prompt</button></span>
          <span><button id="copyAiInputBtn" class="btn" type="button">Copy AI Input</button></span>
          <span><button id="exportAiBundleBtn" class="btn" type="button">Export AI Bundle</button></span>
        </div>
      `;
      if (openGeminiChatLink) {{
        openGeminiChatLink.href = GEMINI_CHAT_URL;
      }}
      const copyBtn = document.getElementById("copyPromptBtn");
      const copyAiInputBtn = document.getElementById("copyAiInputBtn");
      const exportAiBundleBtn = document.getElementById("exportAiBundleBtn");
      if (copyBtn) {{
        copyBtn.addEventListener("click", async () => {{
          const prompt = buildChatPrompt(ep);
          try {{
            await navigator.clipboard.writeText(prompt);
            copyBtn.textContent = "Copied";
            setTimeout(() => (copyBtn.textContent = "Copy Chat Prompt"), 1300);
          }} catch (_) {{
            copyBtn.textContent = "Copy failed";
            setTimeout(() => (copyBtn.textContent = "Copy Chat Prompt"), 1300);
          }}
        }});
      }}
      if (copyAiInputBtn) {{
        copyAiInputBtn.addEventListener("click", async () => {{
          const prompt = buildAiInputPrompt(ep);
          try {{
            await navigator.clipboard.writeText(prompt);
            copyAiInputBtn.textContent = "Copied";
            setTimeout(() => (copyAiInputBtn.textContent = "Copy AI Input"), 1300);
          }} catch (_) {{
            copyAiInputBtn.textContent = "Copy failed";
            setTimeout(() => (copyAiInputBtn.textContent = "Copy AI Input"), 1300);
          }}
        }});
      }}
      if (exportAiBundleBtn) {{
        exportAiBundleBtn.addEventListener("click", () => {{
          const bundle = buildAiInputBundle(ep);
          const blob = new Blob([JSON.stringify(bundle, null, 2)], {{ type: "application/json" }});
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = `ai_input_bundle_${{eid}}.json`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        }});
      }}

      videoNote.textContent = "";
      if (src) {{
        video.src = src;
      }} else {{
        video.removeAttribute("src");
        video.load();
        videoNote.textContent = hasVideo
          ? "Video path exists but not web-accessible. Serve this page from outputs/ root and keep relative video paths."
          : "No video found for this episode | لا يوجد فيديو لهذه الحلقة.";
      }}

      const tier2Raw = ep.tier2_text || ep.tier2;
      const tier3Raw = ep.tier3_text || ep.tier3;
      tier2Box.textContent = toText(tier2Raw);
      tier3Box.textContent = toText(tier3Raw);
      renderTimeline(tier2Timeline, parseSegments(tier2Raw));
      renderTimeline(tier3Timeline, parseSegments(tier3Raw));
      validationBox.textContent = ep.validation ? JSON.stringify(ep.validation, null, 2) : "(missing)";
      const disputes = Array.isArray(ep.disputes) ? ep.disputes.slice(0, 5) : [];
      disputesBox.textContent = disputes.length ? JSON.stringify(disputes, null, 2) : "(none)";
      renderTripletCompareForEpisode(currentEpisodeId);
      renderEvalForEpisode(currentEpisodeId);
      renderVertexChatForEpisode(currentEpisodeId);
    }}

    function initFilter() {{
      const keys = Object.keys(statusCounts).sort();
      statusEl.innerHTML = `<option value="all">All statuses | كل الحالات (${{episodes.length}})</option>` +
        keys.map((k) => `<option value="${{k}}">${{k}} (${{statusCounts[k]}})</option>`).join("");
    }}

    initFilter();
    evalStore = loadLocalEvalStore();
    loadExternalEvalStore();
    loadTripletCompareStore();

    geminiEvalSaveBtn.addEventListener("click", saveCurrentEval);
    geminiEvalClearBtn.addEventListener("click", clearCurrentEval);
    geminiEvalAutoScoreBtn.addEventListener("click", () => {{
      const s = parseScoreFromText(geminiEvalText.value || "");
      if (s === null) {{
        applyScoreBadge(null);
        return;
      }}
      geminiEvalScoreInput.value = String(s);
      applyScoreBadge(s);
    }});
    geminiEvalExportBtn.addEventListener("click", () => {{
      const payload = {{
        generated_at_utc: new Date().toISOString(),
        source: "atlas_review_viewer",
        evaluations: evalStore,
      }};
      const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: "application/json" }});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "gemini_chat_evaluations.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }});
    geminiEvalImportBtn.addEventListener("click", () => geminiEvalImportFile.click());
    geminiEvalImportFile.addEventListener("change", (ev) => {{
      const f = ev.target.files && ev.target.files[0];
      if (!f) return;
      const r = new FileReader();
      r.onload = () => {{
        try {{
          const obj = JSON.parse(String(r.result || "{{}}"));
          let incoming = {{}};
          if (Array.isArray(obj)) {{
            obj.forEach((rec) => {{
              if (!rec || typeof rec !== "object") return;
              const eid = String(rec.episode_id || "");
              if (!eid) return;
              incoming[eid] = rec;
            }});
          }} else if (obj && typeof obj === "object") {{
            if (Array.isArray(obj.evaluations)) {{
              obj.evaluations.forEach((rec) => {{
                if (!rec || typeof rec !== "object") return;
                const eid = String(rec.episode_id || "");
                if (!eid) return;
                incoming[eid] = rec;
              }});
            }} else if (obj.evaluations && typeof obj.evaluations === "object") {{
              incoming = obj.evaluations;
            }} else {{
              incoming = obj;
            }}
          }}
          evalStore = mergeEvalStores(evalStore, incoming);
          saveLocalEvalStore();
          if (currentEpisodeId) renderEvalForEpisode(currentEpisodeId);
        }} catch (_) {{}}
      }};
      r.readAsText(f);
    }});
    video.addEventListener("timeupdate", () => {{
      if (segStopAt == null) return;
      if (video.currentTime >= segStopAt) {{
        video.pause();
        segStopAt = null;
      }}
    }});
    episodeSelectEl.addEventListener("change", () => {{
      const eid = String(episodeSelectEl.value || "");
      if (!eid) return;
      const ep = episodes.find((x) => String(x.episode_id || "") === eid);
      if (ep) selectEpisode(ep);
    }});
    searchEl.addEventListener("input", renderEpisodeSelect);
    statusEl.addEventListener("change", renderEpisodeSelect);
    renderEpisodeSelect();
  </script>
</body>
</html>
"""


def generate_viewer(index_path: Path, out_path: Path, title: str) -> Path:
    payload = _load_json(index_path)
    html = _build_html(payload, title=title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate episodes review HTML viewer.")
    parser.add_argument(
        "--index",
        default="outputs/episodes_review_index.json",
        help="Path to episodes_review_index.json",
    )
    parser.add_argument(
        "--out",
        default="outputs/atlas_review_viewer.html",
        help="Output HTML path",
    )
    parser.add_argument(
        "--title",
        default="Atlas Episode Review Viewer",
        help="Page title",
    )
    args = parser.parse_args()

    out = generate_viewer(Path(args.index).resolve(), Path(args.out).resolve(), title=args.title)
    print(f"[review-viewer] saved: {out}")


if __name__ == "__main__":
    main()
