# Implementation Plan: 4-Way Episode Solver Pipeline

**Branch**: `001-4way-episode-solver` | **Date**: 2026-03-20 | **Spec**: [spec.md](spec.md)  
**Research**: [research.md](research.md) | **Data Model**: [data-model.md](data-model.md)

## Summary

بناء pipeline موثوق لحل حلقات Atlas بـ 4 طرق (Tier2/Tier3 API/Tier3 Chat/Vertex Chat) مع بوابة جودة صارمة (≥95%)، repair loop آلي، وتحسين جودة Chat الآلي. المشروع قائم بالفعل ويحتاج تحسين لا إعادة بناء.

## Technical Context

**Language/Version**: Python 3.10+  
**Primary Dependencies**: Playwright, requests, pyyaml, google-auth, google-generativeai, anthropic  
**Storage**: JSON/JSONL files (outputs/, chat_reviews/, triplet_compare/)  
**Testing**: unittest (tests/)  
**Target Platform**: Linux VPS (headless) + Windows (development)  
**Project Type**: CLI pipeline / automation agent  
**Performance Goals**: حل حلقة في أقل من 10 دقائق  
**Constraints**: ميزانية < $0.5/حلقة، zero tolerance for bad submits  
**Scale/Scope**: مئات الحلقات أسبوعيًا

## Constitution Check

⚠️ `constitution.md` لسه template فاضي.

**المبادئ المستنتجة من الكود**:
- ✅ **Safety-First**: `submit_gate.py` يمنع أي submit غير آمن (5 checks)
- ✅ **Fail-Closed**: missing submit_safe = mismatch = BLOCK (سطر 240 `submit_gate.py`)
- ✅ **Deterministic Validation**: `validator.py` يعمل rule-based بدون LLM
- ✅ **Logging**: كل قرار مسجل في JSONL

## Project Structure

### Generated Plan Artifacts

```text
├── spec.md              # Feature specification (157 lines)
├── plan.md              # This file
├── research.md          # Phase 0 research findings
├── data-model.md        # Entity definitions
├── quickstart.md        # Getting started guide
└── tasks.md             # Task breakdown (36 tasks)
```

### Source Code (الملفات الموجودة بالفعل)

```text
# Core pipeline (اللي هنشتغل عليها)
atlas_triplet_compare.py      # 2102 lines - 4-way judge + video inline
atlas_triplet_batch.py        # batch orchestration
submit_gate.py                # 475 lines - 5-check gate
atlas_repair_loop.py          # 644 lines - repair with Gemini/Vertex
validator.py                  # 1116 lines - deterministic rule engine
pipeline_runner.py            # 1187 lines - multi-pass orchestration
prompts.py                    # 368 lines - prompts + JSON schema
repair_payload_builder.py     # repair payload builder
run_single_episode_4way.sh    # 369 lines - entry point

# Support (قد تحتاج فحص)
atlas_web_auto_solver.py      # browser automation (Chat upload)
atlas_claude_smart_ai2.py     # Claude vision fallback (مستقبلي)
vertex_create_cache.py        # Vertex context cache
atlas_build_vertex_fewshot.py # few-shot bundle builder
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│               run_single_episode_4way.sh                     │
│                  atlas_triplet_batch.py                       │
├───────────┬───────────┬─────────────┬────────────────────────┤
│  Tier2    │ Tier3 API │ Tier3 Chat  │ Vertex Chat            │
│  (draft)  │ (Gemini)  │ (Playwright)│ (cached context)       │
│           │ FPS=8     │ FPS=4 ❌    │                        │
├───────────┴───────────┴─────────────┴────────────────────────┤
│              atlas_triplet_compare.py (Judge)                 │
│              scores + hallucination + winner selection         │
├──────────────────────────────────────────────────────────────┤
│              submit_gate.py (5-Check Gate)                    │
│  1.valid winner → 2.submit_safe match → 3.hallucination      │
│  → 4.validator.py → 5.score ≥ 95                            │
├──────────────────────────────────────────────────────────────┤
│     ┌── safe=True → Submit ✅                                │
│     └── safe=False → atlas_repair_loop.py                    │
│           ├── success → Re-gate → Submit                     │
│           └── fail → manual_queue.jsonl                      │
└──────────────────────────────────────────────────────────────┘
```

## Phase 0: Research Findings (مكتمل)

→ انظر [research.md](research.md)

**أهم النتائج**:
1. **مشكلة الـ Chat**: FPS=4 منخفض جدًا + one-shot بدل multi-turn
2. **الـ Gate**: محكم وآمن (5 checks) — لا يحتاج تغيير جوهري
3. **الـ Repair**: يعمل لكن يحتاج hallucination pre-filter + زيادة max_attempts لـ 3
4. **البنية**: كاملة ومترابطة — تحتاج تحسين لا إعادة كتابة

## Phase 1: Stabilization (أسبوع 1)

### 1.1 التأكد من STRICT_GATE
```diff
# run_single_episode_4way.sh
-STRICT_GATE=${STRICT_GATE:-0}
+STRICT_GATE=1  # NON-NEGOTIABLE
```

### 1.2 فحص submit_gate.py
- ✅ Check 2: missing submit_safe = mismatch = BLOCK (موجود بالفعل)
- ✅ Check 3: hallucination = BLOCK (موجود)
- ✅ Check 5: score < 95 = BLOCK (موجود)
- ⚠️ التأكد من تفعيل `run_validator=True` في كل الاستدعاءات

### 1.3 تحسين Logging
- إضافة `gate_decision_detail` في الـ logging
- تسجيل **سبب** كل قبول/رفض بالتفصيل

## Phase 2: Repair Loop Enhancement (أسبوع 1-2)

### 2.1 زيادة max_attempts
```diff
# atlas_repair_loop.py
-max_attempts: int = 2
+max_attempts: int = 3
```

### 2.2 إضافة hallucination pre-filter
```python
# قبل بدء الـ repair loop:
if gate_result.llm_hallucination_flag:
    return None  # hallucination مش قابلة للإصلاح
```

### 2.3 فلترة الأخطاء
- أخطاء قابلة للإصلاح: verb_start, forbidden_verbs, numerals, narrative_filler
- أخطاء غير قابلة: hallucination, timestamp_corruption, missing_video_content

## Phase 3: Chat Quality Improvement (أسبوع 2-3)

### 3.1 تحسين FPS
```diff
# sample_web_auto_solver.yaml
-optimize_video_target_fps: 4.0
+optimize_video_target_fps: 12.0

-vision_preencode_fps: 4.0
+vision_preencode_fps: 12.0
```

### 3.2 زيادة Settle Time
```diff
-chat_web_upload_settle_min_sec: 8
+chat_web_upload_settle_min_sec: 15
```

### 3.3 محاولة Multi-turn
في `atlas_web_auto_solver.py`، بعد الرد الأول:
- إرسال follow-up: "Review your answer. Are timestamps accurate? Any missed actions?"
- أخذ الرد الثاني كحل نهائي

## Phase 4: Learning Loop (أسبوع 3-4)

### 4.1 Gold Sample Pipeline
تصحيح يدوي → export → few-shot bundle → Vertex cache update

### 4.2 قياس أسبوعي
- نسبة النجاح (pass_rate)
- متوسط الجودة (avg_score)
- تكلفة الحلقة (avg_cost)

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| 4 inference methods | لا يوجد method واحد يحقق 100% reliability | API أحيانًا rate limited, Chat مش reproducible |
| Multi-model support | fallback chain ضروري | نموذج واحد أحيانًا بيفشل |
| Browser automation | Chat الآلي يعطي نتائج محتملة أفضل | API وحده مش كافي |
