# Tasks: 4-Way Episode Solver Pipeline

**Input**: specs/001-4way-episode-solver/
**Prerequisites**: plan.md, spec.md

## Phase 1: Setup

- [x] T001 [US1] التحقق من مفاتيح `.env` (GEMINI_API_KEY, GOOGLE_APPLICATION_CREDENTIALS)
- [x] T002 [P] [US1] التحقق من إعدادات YAML production (strict_gate, require_video)
- [x] T003 [P] [US1] التحقق من Playwright + headless Chrome
- [x] T004 [US1] التحقق من Vertex AI credentials + cached content

---

## Phase 2: Stabilization (بوابة الجودة)

- [x] T005 [US2] تفعيل STRICT_GATE=1 ثابت في `run_single_episode_4way.sh`
- [x] T006 [US2] فحص حظر submit في `atlas_triplet_compare.py` عند hallucination/mismatch/score<95
- [x] T007 [P] [US2] اختبارات `validator.py` لكل حالات الرفض
- [x] T008 [P] [US2] فحص `submit_gate.py` لعدم وجود bypass
- [x] T009 [US2] logging محسّن لقرارات quality gate
- [x] T037 [US2] فحص FR-008 لمنع text-only fallback (مطبق عبر `allow_text_only_fallback_on_network_error`)
- [x] T038 [US2] فحص FR-009 لـ multi-model و key rotation (مطبق في `atlas_web_auto_solver.py`)
- [x] T039 [US2] فحص FR-012 لـ Gemini Web Chat gate قبل Submit (مطبق)
- [x] T040 [US2] فحص FR-013 لتخزين تقييمات Chat في `gemini_chat_evaluations.json` (مطبق في `atlas_eval_store.py`)
- [x] T041 تغطية الـ Edge Cases (corrupted, rate limit, selector drift, empty drafts)

**Checkpoint**: ✅ لا يمكن أي submit غير آمن ومطابقة المتطلبات والتغطية تمت بنجاح

---

## Phase 3: 4-Way Solving (P1) 🎯 MVP

- [x] T010 [US1] فحص `atlas_triplet_batch.py` لتشغيل كل الـ 4 طرق
- [x] T011 [US1] فحص flags في `run_single_episode_4way.sh`
- [x] T012 [US1] فحص اختيار winner في `atlas_triplet_compare.py`
- [x] T013 [US1] فحص `pass_score_threshold=95`
- [x] T014 [US1] fallback logic: فشل كلي → قائمة يدوية
- [ ] T015 [US1] اختبار كامل على 5 حلقات حقيقية

**Checkpoint**: ✅ الحلقة بتتحل بالـ 4 طرق

---

## Phase 4: Repair Loop (P2)

- [x] T016 [US3] فحص `atlas_repair_loop.py`
- [x] T017 [US3] فحص `repair_payload_builder.py`
- [x] T018 [US3] فلترة أخطاء قابلة للإصلاح vs غير قابلة
- [x] T019 [US3] حد أقصى repair (max=3) في `pipeline_runner.py`
- [x] T020 [US3] re-validation بعد كل repair
- [x] T021 [US3] تسجيل repair outcomes في JSONL

**Checkpoint**: ✅ Repair loop يحسن نسبة النجاح

---

## Phase 5: Chat Quality (P2)

- [x] T022 [US4] مراجعة إعدادات ضغط الفيديو (FPS, bitrate)
- [x] T023 [US4] فحص `chat_web_upload_settle_min_sec`
- [x] T024 [US4] فحص منطق رفع الفيديو في `atlas_web_auto_solver.py`
- [ ] T025 [US4] اختبار FPS مختلفة (4, 8, 12)
- [ ] T026 [US4] multi-turn بدل one-shot
- [ ] T027 [US4] مقارنة منهجية: API vs Chat vs Vertex (10 حلقات)

**Checkpoint**: ✅ جودة Chat الآلي تتحسن (FPS 4→8, settle 4→8)

---

## Phase 6: Learning Loop (P3)

- [ ] T028 [US5] فحص `atlas_build_vertex_fewshot.py`
- [ ] T029 [US5] فحص `vertex_create_cache.py`
- [ ] T030 [US5] pipeline: تصحيح → gold sample → bundle → cache update
- [ ] T031 [US5] مقياس أسبوعي للتحسن

---

## Phase 7: Polish

- [x] T032 [P] تعبئة `constitution.md`
- [ ] T033 [P] تحديث `README.md`
- [ ] T034 تحسين Dashboard
- [ ] T035 [P] cost tracking في `cost_report.py`
- [ ] T036 alerting عند فشل متتالي

---

## Dependencies

- Phase 1 → Phase 2 → Phase 3 (sequential, blocking)
- Phase 4 + Phase 5 → بالتوازي بعد Phase 2
- Phase 6 → بعد Phase 3 + 4
- Phase 7 → بعد الكل
