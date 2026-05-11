# Feature Specification: 4-Way Episode Solver Pipeline

**Feature Branch**: `001-4way-episode-solver`  
**Created**: 2026-03-19  
**Status**: Draft  
**Input**: "نظام حل حلقات آلي 4-way مع بوابة جودة 95-100%"

## ملخص (Summary)

نظام أتمتة كامل لحل مهام Atlas الخاصة بالـ OCR/Video Annotation.
النظام بيحل الحلقة بأي طريقة من 4 طرق، والأهم إن الجودة تكون 95% حد أدنى أو 100%.
Claude هيتضاف كـ fallback أخير لو كل الطرق الأربعة فشلت.

## User Scenarios & Testing

### User Story 1 - حل حلقة واحدة بأي طريقة ناجحة من 4 (Priority: P1)

المشغل يشغل النظام على حلقة واحدة (episode). النظام يجرب الـ 4 طرق لإنتاج حل submit-safe:
1. **Tier2 Draft**: مسودة الموظف الأصلية
2. **Tier3 API**: Gemini API مباشرة (video + prompt)
3. **Tier3 Chat**: Gemini Chat عبر المتصفح (Playwright)
4. **Vertex Chat**: Vertex AI مع cached context

النظام يختار أفضل حل يحقق الـ quality gate (≥95%).

**Why this priority**: الهدف الأساسي من المشروع - أي حلقة لازم تتحل بجودة عالية.

**Independent Test**: تشغيل `run_single_episode_4way.sh` على حلقة واحدة والتحقق `quality_pass=True` و`score_pct≥95`.

**Acceptance Scenarios**:

1. **Given** حلقة جديدة بفيديو ومسودة Tier2, **When** يتم تشغيل 4-way pipeline, **Then** طريقة واحدة على الأقل تنتج حل بجودة ≥95%
2. **Given** كل المرشحين أقل من threshold, **When** الـ 4 طرق فشلت, **Then** الحلقة تتحول لقائمة الحل اليدوي ولا يتم submit
3. **Given** solutions from multiple models, **When** they are compared, **Then** the most accurate one is selected as the winner.
4. **Given** مرشح واحد فقط يحقق الـ threshold, **When** الـ judge يقيّم, **Then** المرشح الناجح يُختار كـ winner

---

### User Story 2 - بوابة جودة صارمة تمنع أي submit خاطئ (Priority: P1)

النظام يمنع أي submit لـ Atlas إلا بعد اجتياز بوابة جودة متعددة الطبقات:
- **Validator** (قواعد policy)
- **Judge** (تقييم multimodal مقارن)
- **Hallucination Check**
- **Submit Safety Check** (تطابق winner مع submit_safe_solution)

**Why this priority**: الحساب حساس وأي submit خاطئ = مخاطرة عالية.

**Independent Test**: تشغيل `validator.py` على عينات معروفة النتائج.

**Acceptance Scenarios**:

1. **Given** مرشح بجودة 100% بدون أخطاء, **When** يمر على الـ gate, **Then** `quality_pass=True`
2. **Given** مرشح بـ hallucination, **When** يمر على الـ gate, **Then** `quality_pass=False`
3. **Given** `winner` ≠ `submit_safe_solution`, **When** يوجد mismatch, **Then** الـ gate يمنع الـ submit

---

### User Story 3 - Repair Loop للحلول المرفوضة (Priority: P2)

لما مرشح يفشل بسبب أخطاء قابلة للإصلاح، النظام يحاول يصلحه آليًا (حد أقصى 3 محاولات).

**Why this priority**: زيادة نسبة الحلقات الناجحة.

**Independent Test**: تشغيل repair على عينة فاشلة والتحقق من التحسن.

**Acceptance Scenarios**:

1. **Given** فشل بسبب `verb_start_not_allowed`, **When** repair loop يشتغل, **Then** المرشح المُصلح يبدأ بفعل صحيح
2. **Given** failure due to hallucination, **When** repair loop is triggered, **Then** the failure is treated as fail-closed; the repair loop cannot auto-accept unless a fresh, non-hallucinated result is produced and validated.3. **Given** فشل بعد 3 محاولات, **When** وصل للحد الأقصى, **Then** يتحول للحل اليدوي

---

### User Story 4 - تحسين جودة Gemini Chat الآلي (Priority: P2)

لما المستخدم يرفع الفيديو يدويًا لـ Gemini Chat → نتيجة ممتازة.
لما البرنامج يرفعه آليًا عبر Playwright → نتيجة ضعيفة.
المطلوب: تقليل هذه الفجوة.

**Why this priority**: حل هذه المشكلة يفتح طريقة قوية جدًا للحل الآلي.

**Independent Test**: مقارنة نتائج نفس الحلقة يدويًا vs آليًا.

**Acceptance Scenarios**:

1. **Given** نفس الفيديو, **When** يتم رفعه آليًا, **Then** الجودة ≥ 90% من الجودة اليدوية
2. **Given** فيديو يحتاج ضغط, **When** يتم ضغطه, **Then** الجودة البصرية كافية للـ annotations

---

### User Story 5 - التعلم المستمر من التصحيحات (Priority: P3)

كل تصحيح يدوي يتحول لعينة ذهبية لتحسين الأداء المستقبلي.

**Why this priority**: تحسين مستمر لكن يأتي بعد ضمان الجودة الأساسية.

**Acceptance Scenarios**:

1. **Given** تصحيح يدوي, **When** يتم تصديره, **Then** يظهر في الـ few-shot bundle
2. **Given** 10 gold samples جديدة, **When** يتم تحديث Vertex cache, **Then** نسبة النجاح تتحسن

---

### Edge Cases

- فيديو مش متاح أو corrupted
- كل API keys فشلت بسبب rate limit
- UI selectors في Atlas تتغيرت
- مسودة Tier2 فاضية تمامًا
- حلقة قصيرة جدًا (< 3 ثواني)

## Requirements

### Functional Requirements

- **FR-001**: النظام يدعم 4 طرق لحل الحلقة: Tier2, Tier3 API, Tier3 Chat, Vertex Chat
- **FR-002**: النظام يمنع أي submit لما الجودة أقل من 95%
- **FR-003**: النظام يفحص كل مرشح للـ hallucination
- **FR-004**: النظام يضمن تطابق `winner` مع `submit_safe_solution`
- **FR-005**: النظام يدعم repair loop (حد أقصى 3 محاولات)
- **FR-006**: النظام يحتفظ بسجل كامل لكل محاولة (logs + artifacts)
- **FR-007**: النظام يدعم تشغيل حلقة واحدة أو batch
- **FR-008**: النظام يمنع text-only fallback لما الفيديو مطلوب
- **FR-009**: النظام يدعم multi-model fallback مع key rotation
- **FR-010**: النظام يحول الحلقات الفاشلة لقائمة الحل اليدوي
- **FR-011**: الـ validator يفحص: أفعال مسموحة، أرقام، تداخل timestamps، granularity، forbidden verbs/narrative words
- **FR-012**: النظام يدعم Gemini Web Chat gate قبل Submit
- **FR-013**: النظام يخزن نتائج التقييم في `gemini_chat_evaluations.json`

### Key Entities

- **Episode**: حلقة (فيديو + segments + labels)
- **Segment**: جزء زمني من الفيديو مع label
- **Candidate**: حل مرشح من أي طريقة
- **Judge Result**: نتيجة المقارنة (winner, scores, hallucination flags)
- **Validation Report**: تقرير فحص القواعد
- **Repair Payload**: بيانات إصلاح مبنية على أخطاء validator
- **Gold Sample**: تصحيح يدوي معتمد

## Success Criteria

### Measurable Outcomes

- **SC-001**: نسبة الحلقات بجودة ≥95% لا تقل عن 80%
- **SC-002**: صفر submits بـ hallucination أو mismatch
- **SC-003**: نسبة نجاح repair ≥50%
- **SC-004**: تكلفة الحلقة لا تزيد عن $0.5
- **SC-005**: وقت حل الحلقة لا يزيد عن 10 دقائق
- **SC-006**: نسبة التدخل اليدوي لا تزيد عن 20%

## Assumptions

- Gemini 3.1 Pro قادر على تحليل الفيديو بجودة كافية (مثبت يدويًا)
- مفاتيح API مكونة في `.env`
- VPS + Playwright مهيأ
- Atlas UI selectors مستقرة
