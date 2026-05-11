# Research: 4-Way Episode Solver Pipeline

**Date**: 2026-03-20 | **Branch**: `001-4way-episode-solver`

## Research Summary

تم تحليل الكود المصدري بالكامل لفهم البنية الحالية وتحديد نقاط القوة والضعف.

---

## R1: بنية الـ Pipeline الحالية

**Decision**: البنية الحالية تعمل وتحتاج تحسين لا إعادة بناء

**Rationale**: الكود يحتوي بالفعل على كل المكونات الأساسية:
- `atlas_triplet_compare.py` (2102 سطر): judge كامل مع 4-way comparison، video inline، parsing متعدد الأشكال
- `submit_gate.py` (475 سطر): 5-check gate محكم (winner validity → submit_safe match → hallucination → validator → score)
- `atlas_repair_loop.py` (644 سطر): repair loop كامل مع Gemini API + Vertex AI fallback
- `validator.py` (1116 سطر): rule engine شامل

**Alternatives considered**: إعادة كتابة Pipeline من الصفر — مرفوض لأن المكونات الحالية شاملة ومترابطة.

---

## R2: مشكلة Chat اليدوي vs الآلي (المشكلة الرئيسية)

**Decision**: المشكلة في 5 عوامل، أهمها ضغط الفيديو وطريقة التفاعل

**Rationale - التحليل التقني**:

### 1. ضغط الفيديو (CRITICAL)
من `atlas_triplet_compare.py` سطر 343-372:
```python
# الضغط الحالي:
"-vf", "scale='min(960,iw)':-2:flags=lanczos,fps=8",
"-crf", "30",  # جودة منخفضة
```
من `sample_web_auto_solver.yaml`:
```yaml
optimize_video_target_fps: 4.0  # منخفض جدًا!
vision_preencode_fps: 4.0       # منخفض جدًا!
```
**المشكلة**: FPS=4 يعني 4 إطارات في الثانية فقط. الفيديو اليدوي يُرفع بالجودة الأصلية (24-30 FPS).

### 2. طريقة التفاعل: One-shot vs Multi-turn
- يدويًا: المستخدم يرفع الفيديو → يحاور Gemini → يسأل أسئلة متابعة
- آليًا: يرفع الفيديو → يرسل prompt واحد → يأخذ الرد مباشرة
- المحادثة المتعددة الأطراف تعطي نتائج أفضل لأن الـ model يراجع حله

### 3. Upload Settle Time
من YAML: `chat_web_upload_settle_min_sec: 8` — ممكن مش كافي لفيديوهات كبيرة

### 4. Session State
الجلسة اليدوية قد تستخدم إعدادات مختلفة (model version، system prompt مخفي)

### 5. Context Loss
في الـ Chat الآلي، كل جلسة بتكون fresh بدون history

---

## R3: بنية الـ Submit Gate

**Decision**: Gate محكم وآمن — لا يحتاج تغيير جوهري

**Rationale**: من `submit_gate.py`:
- Check 1: `winner` لازم يكون valid (tier2/api/chat/vertex_chat)
- Check 2: `submit_safe_solution` لازم يطابق `winner` (missing = mismatch = BLOCK)
- Check 3: hallucination flag لازم يكون False
- Check 4: validator.py لازم يمر (deterministic rule check)
- Check 5: score لازم يكون ≥ threshold

**ملاحظة مهمة**: Check 2 فيه CRITICAL FIX: لو `submit_safe` مش موجود = mismatch = BLOCK. ده ممتاز للأمان.

---

## R4: بنية الـ Repair Loop

**Decision**: Repair loop موجود وفعال لكن يحتاج تحسينات

**Rationale**: من `atlas_repair_loop.py`:
- `max_attempts=2` (الحد الافتراضي) — ممكن نزوده لـ 3
- بيعمل preserve للـ timestamps (سطر 486-501) — ممتاز
- بيرفض لو count الـ segments اختلف (سطر 488-494) — safety check
- بيكتب في `repair_history.jsonl` و `manual_queue.jsonl` — logging كامل
- مفيش فلترة للأخطاء القابلة للإصلاح vs غير القابلة (hallucination)

**Alternatives**: إضافة hallucination pre-check قبل محاولة الإصلاح

---

## R5: إعدادات Video لكل طريقة

**Decision**: إعدادات الفيديو تختلف بين الطرق

| الطريقة | FPS | Max Size | ملاحظات |
|---------|-----|----------|---------|
| Tier3 API (inline) | 8 | 20MB | `_compress_video_for_inline()` |
| Tier3 Chat (Playwright) | 4 | يختلف | `optimize_video_target_fps` |
| Vertex Chat | API-dependent | varies | cached context |

---

## R6: Key Dependencies

| Dependency | Version | Purpose |
|-----------|---------|---------|
| Playwright | latest | Browser automation for Gemini Chat |
| requests | any | HTTP calls to Gemini/Vertex APIs |
| pyyaml | any | Config loading |
| google-auth | any | Vertex AI authentication |
| google-generativeai | any | Gemini SDK (optional) |
| ffmpeg | system | Video compression |
| rclone | system | Google Drive downloads |
