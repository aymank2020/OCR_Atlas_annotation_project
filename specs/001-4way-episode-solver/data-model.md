# Data Model: 4-Way Episode Solver Pipeline

**Date**: 2026-03-20 | **Branch**: `001-4way-episode-solver`

## Core Entities

### Episode
حلقة واحدة تحتوي على مقطع فيديو ومجموعة من segments مع labels.

| Field | Type | Description |
|-------|------|-------------|
| episode_id | string | معرّف فريد (Atlas episode ID) |
| video_path | string | مسار الفيديو (local أو Drive reference) |
| video_duration_sec | float | مدة الفيديو بالثواني |
| segments | Segment[] | مجموعة الأجزاء الزمنية |

### Segment
جزء زمني واحد من الفيديو مع label يصف الحدث.

| Field | Type | Constraints |
|-------|------|-------------|
| segment_index | int | 1-based, unique within episode |
| start_sec | float | ≥ 0, < end_sec |
| end_sec | float | > start_sec |
| label | string | Must start with action verb, no numerals, no body parts |
| duration_sec | float | = end_sec - start_sec, > 0 |

**Validation Rules** (from `validator.py`):
- Label MUST start with allowed action verb
- No numerals (use words: "two" not "2")
- No intent language ("prepare to", "try to")
- No body part references
- No narrative fillers ("then", "another", "continue")
- Max 2 atomic actions per label
- "No Action" only for true inactivity

### Candidate
حل مرشح لحلقة من إحدى الطرق الأربعة.

| Field | Type | Description |
|-------|------|-------------|
| source | enum | tier2 / api / chat / vertex_chat |
| segments | Segment[] | الحل المقترح |
| file_path | string | مسار ملف الحل |
| score | int | 0-100, from judge |
| hallucination | bool | هل يحتوي هلوسة؟ |
| major_issues | string[] | قائمة المشاكل الكبرى |

### JudgeResult
نتيجة المقارنة بين المرشحين الأربعة.

| Field | Type | Description |
|-------|------|-------------|
| winner | enum | tier2/api/chat/vertex_chat/none |
| submit_safe_solution | enum | tier2/api/chat/vertex_chat/none |
| scores | {tier2, api, chat, vertex_chat: int} | درجات 0-100 |
| hallucination | {tier2, api, chat, vertex_chat: bool} | flags |
| major_issues | {tier2, api, chat, vertex_chat: string[]} | مشاكل |
| best_reason_short | string | سبب اختيار الفائز |
| final_recommendation | string | التوصية النهائية |

### SubmitGateResult
نتيجة بوابة الأمان قبل Submit.

| Field | Type | Description |
|-------|------|-------------|
| episode_id | string | معرّف الحلقة |
| safe | bool | True = approved for submit |
| winner | string | المرشح الفائز |
| reason | string | سبب القرار (machine-readable) |
| score_pct | int? | درجة الفائز |
| validator_ok | bool? | هل اجتاز الـ validator |
| validator_major_fails | string[] | أخطاء validator الكبرى |
| llm_hallucination_flag | bool | هل فيه hallucination |
| submit_safe_mismatch | bool | هل فيه عدم تطابق |
| checks_performed | string[] | الفحوصات اللي تمت |

### RepairAttempt
Individual step within a repair loop.

| Field | Type | Description |
|-------|------|-------------|
| attempt_id | string | UID for the attempt |
| timestamp | string (ISO) | When it started |
| tool | string | e.g. "gemini_repair" |
| input_segments | Segment[] | Uncorrected segments |
| output_segments | Segment[]? | Corrected segments (if any) |
| success | bool | Did it fix the target error? |
| error_message | string? | Error if tool failed |
| duration_ms | int | Execution time |

### RepairLoopResult
نتيجة محاولة إصلاح حل فاشل.

| Field | Type | Description |
|-------|------|-------------|
| episode_id | string | معرّف الحلقة |
| success | bool | هل الإصلاح نجح |
| final_segments | Segment[]? | الأجزاء بعد الإصلاح |
| attempts | RepairAttempt[] | تفاصيل كل محاولة |
| total_duration_sec | float | الوقت الإجمالي بالثواني |
| failure_reason | string | سبب الفشل (إن وجد) |
| queued_for_manual | bool | هل تم تحويله للحل اليدوي |

## State Transitions

```
Episode Created
    ↓
[Generate 4 Candidates]
    ↓
tier2/api/chat/vertex_chat → Candidate[]
    ↓
[Judge Compare] → JudgeResult
    ↓
[Submit Gate] → SubmitGateResult
    ↓
    ├── safe=True → Submit to Atlas
    └── safe=False
         ↓
    [Repair Loop] → RepairLoopResult
         ↓
         ├── success=True → Re-gate → Submit
         └── success=False → Manual Queue
```

## Storage (File-based)

| File | Format | Content |
|------|--------|---------|
| `outputs/triplet_compare_<eid>.json` | JSON | JudgeResult + metadata |
| `outputs/manual_queue.jsonl` | JSONL | Episodes for manual review |
| `outputs/repair_history.jsonl` | JSONL | Repair attempt logs |
| `outputs/repaired/repaired_<eid>.json` | JSON | Successfully repaired segments |
| `outputs/gemini_usage.jsonl` | JSONL | API usage + cost tracking |
| `chat_reviews/<eid>/` | dir | Chat-based evaluation results |
