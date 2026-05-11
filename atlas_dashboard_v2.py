"""
atlas_dashboard_v2.py — Enhanced production dashboard.

New metrics vs v1:
- Submit Gate pass/fail rate (validator_ok breakdown)
- Repair loop stats (success rate, avg attempts)
- Manual queue size + oldest unresolved
- Knowledge base stats (lessons by category)
- 7-day quality trend chart
- Cost per safe episode
- Top validator failure types

Usage:
  python atlas_dashboard_v2.py --outputs-dir outputs
  python atlas_dashboard_v2.py --outputs-dir outputs --open
"""

from __future__ import annotations

import argparse
import html
import json
import webbrowser
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Data loaders ──────────────────────────────────────────────────────

def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _to_float(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return d


def _to_int(v: Any, d: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return d


# ── Metric computation ────────────────────────────────────────────────

def compute_metrics(outputs_dir: Path) -> Dict[str, Any]:
    m: Dict[str, Any] = {}
    m["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    m["outputs_dir"] = str(outputs_dir)

    # ── Triplet compare results
    results = _load_jsonl(outputs_dir / "triplet_compare_results.jsonl")
    total = len(results)
    quality_pass = sum(1 for r in results if r.get("quality_pass"))
    validator_ok = sum(1 for r in results if r.get("validator_ok") is True)
    validator_fail = sum(1 for r in results if r.get("validator_ok") is False)
    llm_only_pass = quality_pass - validator_ok  # passed LLM gate but not validator

    winner_dist: Dict[str, int] = {}
    fail_reasons: Dict[str, int] = {}
    validator_fails_by_type: Dict[str, int] = {}

    for r in results:
        w = str(r.get("winner") or "none")
        winner_dist[w] = winner_dist.get(w, 0) + 1
        if not r.get("quality_pass"):
            reason = str(r.get("reason") or "unknown").split(":")[-1].strip()
            fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
        for fail_type in (r.get("validator_major_fails") or []):
            ft = str(fail_type)
            validator_fails_by_type[ft] = validator_fails_by_type.get(ft, 0) + 1

    m["total_episodes"] = total
    m["quality_pass"] = quality_pass
    m["quality_fail"] = total - quality_pass
    m["pass_rate_pct"] = round(float(quality_pass) / total * 100, 1) if total else 0.0
    m["validator_ok"] = validator_ok
    m["validator_fail"] = validator_fail
    m["winner_distribution"] = dict(winner_dist)
    m["top_fail_reasons"] = sorted(fail_reasons.items(), key=lambda x: -x[1])[:8]
    m["top_validator_fail_types"] = sorted(validator_fails_by_type.items(), key=lambda x: -x[1])[:8]

    # ── Repair history
    repairs = _load_jsonl(outputs_dir / "repair_history.jsonl")
    repair_success = sum(1 for r in repairs if any(
        a.get("gate_passed") for a in (r.get("attempts") or [])
    ))
    m["repair_total"] = len(repairs)
    m["repair_success"] = repair_success
    m["repair_success_rate"] = round(repair_success / len(repairs) * 100, 1) if repairs else 0
    avg_attempts = (
        sum(r.get("total_attempts", 1) for r in repairs) / len(repairs)
        if repairs else 0
    )
    m["repair_avg_attempts"] = round(avg_attempts, 2)

    # ── Manual queue
    manual_queue = _load_jsonl(outputs_dir / "manual_queue.jsonl")
    # Deduplicate by episode_id, keep latest
    manual_by_ep: Dict[str, Dict] = {}
    for row in manual_queue:
        eid = str(row.get("episode_id") or "").strip()
        if eid:
            manual_by_ep[eid] = row
    m["manual_queue_size"] = len(manual_by_ep)
    m["manual_queue_episodes"] = [
        {"episode_id": eid, "reason": str(v.get("reason", ""))[:60],
         "winner": str(v.get("winner", "")),
         "queued_at": str(v.get("queued_at_utc", ""))[:16]}
        for eid, v in list(manual_by_ep.items())[-10:]
    ]

    # ── Cost metrics
    usage = _load_jsonl(outputs_dir / "gemini_usage.jsonl")
    total_cost = sum(_to_float(r.get("estimated_cost_usd", 0)) for r in usage)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_cost = sum(
        _to_float(r.get("estimated_cost_usd"), 0.0) for r in usage
        if str(r.get("ts_utc") or "").startswith(today_str)
    )
    cost_per_safe = (total_cost / quality_pass) if quality_pass > 0 else 0.0
    m["total_cost_usd"] = round(total_cost, 4)
    m["today_cost_usd"] = round(today_cost, 4)
    m["cost_per_safe_episode"] = round(cost_per_safe, 4)

    # Cost by model
    cost_by_model: Dict[str, float] = defaultdict(float)
    for r in usage:
        cost_by_model[str(r.get("model", "unknown"))] += _to_float(r.get("estimated_cost_usd", 0))
    m["cost_by_model"] = sorted(cost_by_model.items(), key=lambda x: -x[1])[:6]

    # ── 7-day quality trend
    trend: Dict[str, Dict[str, int]] = {}
    for r in results:
        # Try to get date from result file modification or queued_at
        date_str = ""
        result_path = outputs_dir / "triplet_compare" / f"triplet_compare_{r.get('episode_id','')}.json"
        if result_path.exists():
            ts = result_path.stat().st_mtime
            date_key = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            date_display = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d")
        if not date_key:
            continue
        if date_key not in trend:
            trend[date_key] = {"display": date_display, "pass": 0, "fail": 0}
        if r.get("quality_pass"):
            trend[date_key]["pass"] += 1
        else:
            trend[date_key]["fail"] += 1
    
    sorted_trend = sorted(trend.items())[-7:]
    m["trend_7d"] = [
        {"date": v["display"], "pass": v["pass"], "fail": v["fail"]}
        for _, v in sorted_trend
    ]

    # ── Knowledge base stats
    lessons_path = outputs_dir / "knowledge" / "policy_lessons.jsonl"
    lessons = _load_jsonl(lessons_path)
    by_cat: Dict[str, int] = defaultdict(int)
    by_src: Dict[str, int] = defaultdict(int)
    for lesson in lessons:
        by_cat[str(lesson.get("category", "general"))] += 1
        by_src[str(lesson.get("source", "unknown"))] += 1
    m["knowledge_total"] = len(lessons)
    m["knowledge_by_category"] = dict(sorted(by_cat.items(), key=lambda x: -x[1]))
    m["knowledge_by_source"] = dict(by_src)

    # ── Episode status breakdown
    review_index = _load_json(outputs_dir / "episodes_review_index.json", {})
    episodes = review_index.get("episodes", []) if isinstance(review_index, dict) else []
    status_counts: Dict[str, int] = defaultdict(int)
    for ep in episodes:
        if isinstance(ep, dict):
            status_counts[str(ep.get("review_status", "unknown"))] += 1
    m["episode_status"] = dict(status_counts)
    m["episodes_total_index"] = len(episodes)

    return m


# ── HTML generation ───────────────────────────────────────────────────

def _pct_color(pct: float) -> str:
    if pct >= 90:
        return "#22c55e"
    if pct >= 70:
        return "#f59e0b"
    return "#ef4444"


def _kpi_card(title: str, value: str, subtitle: str = "", color: str = "#6366f1") -> str:
    return f"""
    <div class="kpi-card">
      <div class="kpi-label">{title}</div>
      <div class="kpi-value" style="color:{color}">{value}</div>
      {f'<div class="kpi-sub">{subtitle}</div>' if subtitle else ''}
    </div>"""


def generate_html(m: Dict[str, Any]) -> str:
    pass_rate = m.get("pass_rate_pct", 0)
    repair_rate = m.get("repair_success_rate", 0)

    # Trend chart data
    trend = m.get("trend_7d", [])
    trend_labels = json.dumps([t["date"] for t in trend])
    trend_pass = json.dumps([t["pass"] for t in trend])
    trend_fail = json.dumps([t["fail"] for t in trend])

    # Top fail reasons table rows
    fail_rows = "".join(
        f"<tr><td>{html.escape(r)}</td><td class='num'>{c}</td></tr>"
        for r, c in m.get("top_fail_reasons", [])
    )
    # Top validator fail types
    val_fail_rows = "".join(
        f"<tr><td>{html.escape(r)}</td><td class='num'>{c}</td></tr>"
        for r, c in m.get("top_validator_fail_types", [])
    )
    # Winner distribution
    winner_rows = "".join(
        f"<tr><td>{html.escape(w)}</td><td class='num'>{c}</td></tr>"
        for w, c in m.get("winner_distribution", {}).items()
    )
    # Manual queue rows
    queue_rows = "".join(
        f"<tr><td>{html.escape(q['episode_id'][:20])}</td><td>{html.escape(q['winner'])}</td>"
        f"<td>{html.escape(q['reason'][:50])}</td><td>{html.escape(q['queued_at'])}</td></tr>"
        for q in m.get("manual_queue_episodes", [])
    )
    # Knowledge rows
    know_rows = "".join(
        f"<tr><td>{html.escape(cat)}</td><td class='num'>{cnt}</td></tr>"
        for cat, cnt in m.get("knowledge_by_category", {}).items()
    )
    # Cost by model
    cost_rows = "".join(
        f"<tr><td>{html.escape(model[:35])}</td><td class='num'>${cost:.4f}</td></tr>"
        for model, cost in m.get("cost_by_model", [])
    )
    # Episode status
    status_rows = "".join(
        f"<tr><td>{html.escape(status)}</td><td class='num'>{cnt}</td></tr>"
        for status, cnt in m.get("episode_status", {}).items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Atlas Pipeline Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #f1f5f9; --surface: #ffffff; --border: #e2e8f0;
    --text: #1e293b; --sub: #64748b; --green: #10b981;
    --yellow: #f59e0b; --red: #ef4444; --blue: #4f46e5;
    --purple: #8b5cf6;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
          font-size: 14px; line-height: 1.5; }}
  header {{ background: var(--surface); border-bottom: 1px solid var(--border);
            padding: 16px 24px; display: flex; align-items: center; gap: 12px; }}
  header h1 {{ font-size: 18px; font-weight: 700; }}
  header .badge {{ background: var(--blue); color: #fff; font-size: 11px;
                   padding: 2px 8px; border-radius: 999px; }}
  .generated {{ font-size: 12px; color: var(--sub); margin-left: auto; }}
  main {{ padding: 24px; max-width: 1400px; margin: 0 auto; }}

  .section-title {{ font-size: 13px; font-weight: 600; color: var(--sub);
                    text-transform: uppercase; letter-spacing: .05em;
                    margin: 24px 0 12px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
               gap: 12px; }}
  .kpi-card {{ background: var(--surface); border: 1px solid var(--border);
               border-radius: 10px; padding: 16px; }}
  .kpi-label {{ font-size: 12px; color: var(--sub); margin-bottom: 4px; }}
  .kpi-value {{ font-size: 28px; font-weight: 700; }}
  .kpi-sub {{ font-size: 12px; color: var(--sub); margin-top: 4px; }}

  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }}
  @media (max-width: 900px) {{
    .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
  }}

  .card {{ background: var(--surface); border: 1px solid var(--border);
           border-radius: 10px; padding: 16px; }}
  .card-title {{ font-size: 13px; font-weight: 600; margin-bottom: 12px;
                 color: var(--sub); text-transform: uppercase; letter-spacing: .04em; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ font-size: 11px; color: var(--sub); text-transform: uppercase; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; color: var(--yellow); }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: rgba(255,255,255,.03); }}

  .progress-bar {{ background: var(--border); border-radius: 4px; height: 8px; overflow: hidden; }}
  .progress-fill {{ height: 100%; border-radius: 4px; transition: width .3s; }}

  .alert {{ background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.3);
            border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }}
  .alert-title {{ color: var(--red); font-weight: 600; margin-bottom: 4px; }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; }}
  .tag-green {{ background: rgba(34,197,94,.2); color: var(--green); }}
  .tag-red {{ background: rgba(239,68,68,.2); color: var(--red); }}
  .tag-yellow {{ background: rgba(245,158,11,.2); color: var(--yellow); }}
  canvas {{ max-height: 200px; }}
</style>
</head>
<body>
<header>
  <h1>🎯 Atlas Pipeline Dashboard</h1>
  <span class="badge">Production</span>
  <span class="badge" style="background:#334155">v2</span>
  <span class="generated">Generated: {m.get("generated_at", "")}</span>
</header>
<main>

  <!-- Alert: Manual queue -->
  {"" if m.get("manual_queue_size", 0) == 0 else f'''
  <div class="alert">
    <div class="alert-title">⚠️ Manual Review Required</div>
    {m.get("manual_queue_size")} episode(s) blocked by gate and need human review.
    Check <code>outputs/manual_queue.jsonl</code>
  </div>'''}

  <!-- KPIs row 1 -->
  <div class="section-title">Quality Gate</div>
  <div class="kpi-grid">
    {_kpi_card("Pass Rate", f"{pass_rate}%",
               f"{m.get('quality_pass',0)}/{m.get('total_episodes',0)} episodes",
               _pct_color(pass_rate))}
    {_kpi_card("Gate Approved", str(m.get("quality_pass", 0)),
               "validator + LLM", "#22c55e")}
    {_kpi_card("Gate Blocked", str(m.get("quality_fail", 0)),
               "requires repair/manual", "#ef4444")}
    {_kpi_card("Validator ✓", str(m.get("validator_ok", 0)),
               "deterministic pass", "#22c55e")}
    {_kpi_card("Validator ✗", str(m.get("validator_fail", 0)),
               "policy violations", "#ef4444")}
    {_kpi_card("Manual Queue", str(m.get("manual_queue_size", 0)),
               "need human review",
               "#ef4444" if m.get("manual_queue_size", 0) > 0 else "#22c55e")}
  </div>

  <!-- KPIs row 2 -->
  <div class="section-title">Repair Loop</div>
  <div class="kpi-grid">
    {_kpi_card("Repair Attempts", str(m.get("repair_total", 0)),
               "total repair runs")}
    {_kpi_card("Repair Success", f"{repair_rate}%",
               f"{m.get('repair_success',0)} repaired",
               _pct_color(repair_rate))}
    {_kpi_card("Avg Attempts", str(m.get("repair_avg_attempts", 0)),
               "per repair episode")}
  </div>

  <!-- KPIs row 3 -->
  <div class="section-title">Cost</div>
  <div class="kpi-grid">
    {_kpi_card("Total Cost", f"${m.get('total_cost_usd', 0):.2f}",
               "all time", "#a855f7")}
    {_kpi_card("Today", f"${m.get('today_cost_usd', 0):.2f}",
               "UTC day", "#a855f7")}
    {_kpi_card("Cost/Safe Ep", f"${m.get('cost_per_safe_episode', 0):.3f}",
               "per approved episode", "#a855f7")}
    {_kpi_card("Knowledge", str(m.get("knowledge_total", 0)),
               "policy lessons", "#6366f1")}
  </div>

  <!-- Charts + tables -->
  <div class="section-title">7-Day Quality Trend</div>
  <div class="card" style="max-width:700px">
    <canvas id="trendChart"></canvas>
  </div>

  <div class="grid-2" style="margin-top:16px">
    <!-- Fail reasons -->
    <div class="card">
      <div class="card-title">Top Gate Failure Reasons</div>
      <table>
        <thead><tr><th>Reason</th><th>Count</th></tr></thead>
        <tbody>{fail_rows or "<tr><td colspan='2'>None</td></tr>"}</tbody>
      </table>
    </div>
    <!-- Validator failures -->
    <div class="card">
      <div class="card-title">Top Validator Fail Types</div>
      <table>
        <thead><tr><th>Policy Violation</th><th>Count</th></tr></thead>
        <tbody>{val_fail_rows or "<tr><td colspan='2'>None</td></tr>"}</tbody>
      </table>
    </div>
  </div>

  <div class="grid-3" style="margin-top:16px">
    <!-- Winner distribution -->
    <div class="card">
      <div class="card-title">Winner Distribution</div>
      <table>
        <thead><tr><th>Candidate</th><th>Count</th></tr></thead>
        <tbody>{winner_rows or "<tr><td colspan='2'>No data</td></tr>"}</tbody>
      </table>
    </div>
    <!-- Cost by model -->
    <div class="card">
      <div class="card-title">Cost by Model</div>
      <table>
        <thead><tr><th>Model</th><th>USD</th></tr></thead>
        <tbody>{cost_rows or "<tr><td colspan='2'>No data</td></tr>"}</tbody>
      </table>
    </div>
    <!-- Episode status -->
    <div class="card">
      <div class="card-title">Episode Status</div>
      <table>
        <thead><tr><th>Status</th><th>Count</th></tr></thead>
        <tbody>{status_rows or "<tr><td colspan='2'>No index</td></tr>"}</tbody>
      </table>
    </div>
  </div>

  <div class="grid-2" style="margin-top:16px">
    <!-- Manual queue -->
    <div class="card">
      <div class="card-title">📋 Manual Queue (latest 10)</div>
      {"<p style='color:var(--green);font-size:12px'>Queue is empty ✓</p>" if not m.get("manual_queue_episodes") else f'''
      <table>
        <thead><tr><th>Episode</th><th>Winner</th><th>Reason</th><th>Queued</th></tr></thead>
        <tbody>{queue_rows}</tbody>
      </table>'''}
    </div>
    <!-- Knowledge base -->
    <div class="card">
      <div class="card-title">📚 Knowledge Base</div>
      <p style="font-size:12px;color:var(--sub);margin-bottom:8px">
        Sources: {", ".join(f"{html.escape(s)}: {c}" for s, c in m.get("knowledge_by_source", {}).items()) or "none"}
      </p>
      <table>
        <thead><tr><th>Category</th><th>Lessons</th></tr></thead>
        <tbody>{know_rows or "<tr><td colspan='2'>No lessons collected</td></tr>"}</tbody>
      </table>
    </div>
  </div>

</main>

<script>
const ctx = document.getElementById("trendChart");
if (ctx) {{
  new Chart(ctx, {{
    type: "bar",
    data: {{
      labels: {trend_labels},
      datasets: [
        {{
          label: "Pass",
          data: {trend_pass},
          backgroundColor: "rgba(34,197,94,0.7)",
          borderRadius: 4,
        }},
        {{
          label: "Fail",
          data: {trend_fail},
          backgroundColor: "rgba(239,68,68,0.7)",
          borderRadius: 4,
        }},
      ],
    }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ labels: {{ color: "#94a3b8", font: {{ size: 12 }} }} }},
      }},
      scales: {{
        x: {{ ticks: {{ color: "#94a3b8" }}, grid: {{ color: "#1e293b" }} }},
        y: {{ ticks: {{ color: "#94a3b8" }}, grid: {{ color: "#334155" }}, beginAtZero: true }},
      }},
    }},
  }});
}}
</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate enhanced Atlas dashboard v2")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--out", default="", help="Output path (default: outputs/atlas_dashboard.html)")
    parser.add_argument("--open", action="store_true", help="Open in browser after generating")
    args = parser.parse_args()

    outputs_dir = Path(args.outputs_dir).resolve()
    out_path = Path(args.out) if args.out else outputs_dir / "atlas_dashboard.html"

    print(f"[dashboard-v2] computing metrics from: {outputs_dir}")
    metrics = compute_metrics(outputs_dir)
    html = generate_html(metrics)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"[dashboard-v2] written: {out_path}")

    # Print summary
    print(f"[dashboard-v2] pass_rate={metrics['pass_rate_pct']}% "
          f"({metrics['quality_pass']}/{metrics['total_episodes']})")
    print(f"[dashboard-v2] validator_ok={metrics['validator_ok']} "
          f"validator_fail={metrics['validator_fail']}")
    print(f"[dashboard-v2] repair_success_rate={metrics['repair_success_rate']}%")
    print(f"[dashboard-v2] manual_queue={metrics['manual_queue_size']} episodes")
    print(f"[dashboard-v2] total_cost=${metrics['total_cost_usd']:.4f} "
          f"cost_per_safe=${metrics['cost_per_safe_episode']:.4f}")
    print(f"[dashboard-v2] knowledge_lessons={metrics['knowledge_total']}")

    if args.open:
        webbrowser.open(f"file://{out_path}")


if __name__ == "__main__":
    main()
