# وثيقة تسليم عميقة إلى Claude Opus 4.6
**التاريخ المرجعي:** 19 مارس 2026  
**المشروع:** OCR Annotation Atlas  
**المالك:** Ayman  
**الهدف من هذه الوثيقة:** إعطاء صورة كاملة، دقيقة، وصريحة عن الوضع الحالي، لماذا فشلنا، وما المطلوب هندسيًا للوصول إلى حل Production-Grade.

---

## 1) الملخص التنفيذي
نقوم ببناء نظام آلي لحل مهام Atlas الخاصة بالـ OCR/Video Annotation مع بوابة جودة صارمة قبل أي Submit.

النظام وصل لمرحلة تشغيل متقدمة (تشغيل حلقة مفردة، مقارنة 4 حلول، generation/review/viewer/dashboard)، لكنه **فشل حتى الآن في تحقيق نجاح 100% بجودة submit-safe** رغم تعديلات كثيرة على البرومبتات، إدارة المفاتيح، Vertex cache، وتحسينات البايبلاين.

**تصريح مطلوب وصريح:**  
> فشلنا في تعديل الحل الحالي للوصول إلى نسبة نجاح 100% بشكل موثوق، وتم صرف أكثر من 90$ مع نتائج غير مرضية.

---

## 2) أهداف المشروع (النسخة الحقيقية)
1. أتمتة حل الحلقات مع أقل تدخل بشري ممكن.
2. منع أي Submit خطر قد يسبب خسارة الحساب.
3. مقارنة متعددة المصادر قبل القرار:
   - Tier2 (حل الموظف)
   - Tier3 API
   - Tier3 Gemini Chat
   - Vertex Chat
4. الوصول إلى **submit-safe reliability** عالية جدًا.
5. تقليل التكلفة التشغيلية، ويفضل التشغيل بنموذج واحد مستقبلاً.

---

## 3) تعريف النجاح والفشل
### تعريف النجاح الحقيقي
- ليس مجرد score مرتفع.
- النجاح = `winner` آمن + `submit_safe_solution` مطابق + لا hallucination + اجتياز gate.

### تعريف الفشل الحالي
- فائز منخفض الجودة.
- أو `submit_safe_solution != winner`.
- أو وجود hallucination عند الفائز.

---

## 4) الوضع الحالي للمنظومة (Current State)
### A) مكونات أساسية موجودة
- `atlas_web_auto_solver.py`: أتمتة المتصفح واستخراج/تجهيز المهمة.
- `atlas_triplet_batch.py`: تشغيل batch للمقارنة.
- `atlas_triplet_compare.py`: judge + scoring + hallucination flags.
- `run_single_episode_4way.sh`: تشغيل حلقة واحدة 4-way.
- `safe_update_preserve_local.sh`: تحديث آمن مع حفظ `.env` و`atlas_auth`.
- `vertex_create_cache.py`: إنشاء Vertex cached context.
- `atlas_build_vertex_fewshot.py`: تجميع Few-shot/context bundle من نتائج المقارنات.
- `sample_web_auto_solver.yaml`: إعدادات auth/models/gates/context.

### B) ما تم تحسينه مؤخرًا
- تم تمرير Tier2 draft للـ timed-label generation (API/Chat/Vertex) بدل التوليد الأعمى.
- تم إضافة سياسات stricter في prompt:
  - gapless timeline
  - منع intent language
  - strict action-policy
- تم دعم `STRICT_GATE` و`FORCE_REGENERATE` في تشغيل الحلقة المفردة.
- تم تحسين سلوك Vertex compare gate + cached content.

---

## 5) سجل المشاكل الواقعية (What actually happened)
### مشاكل بنية وتشغيل
- مشاكل بيئة Python/PEP668 وغياب venv الصحيح في أكثر من مرة.
- مشكلة مفقودات مفاتيح `.env` وإعادة استرجاعها من stash/backup.
- مشكلة `google-auth` و`playwright` وتهيئة headless على Linux.
- مشكلة `module 'yaml' has no attribute 'safe_load'` بسبب تضارب package.
- تعارضات autostash أثناء safe update.

### مشاكل جودة مباشرة
- نتائج كثيرة أقل من threshold.
- winner أحيانًا يكون “أفضل السيئين”.
- حالات hallucination واضحة.
- عدم تطابق `submit_safe_solution` مع `winner` في حالات حرجة.

---

## 6) أدلة الفشل (Evidence)
أمثلة نتائج تشغيل فعلية:
- حالة: `winner=api`, `score=55`, `reason=winner_hallucination`.
- حالة: `winner=tier2`, `score=45`, `submit_safe_solution=none`, `reason=submit_safe_mismatch`.
- حالات عديدة أقل من threshold (95) رغم وجود مفاتيح وتشغيل كامل.

الخلاصة العملية:
- المنظومة تعمل تقنيًا (تشغيل/توليد/مقارنة).
- لكنها غير موثوقة بعد كمنظومة auto-submit.

---

## 7) لماذا التعديلات لم تكفِ؟
1. اعتماد زائد على prompt engineering بدون طبقة rule-repair حتمية قوية.
2. judge قادر يحدد المشاكل لكنه لا يحولها تلقائيًا لحل نهائي submit-safe.
3. ضعف في timestamp alignment الدقيق لبعض المرشحين.
4. عدم وجود حلقة تعلم منظمة من “gold corrections” إلى inference policy بشكل دوري وثابت.
5. pipeline يوازن بين التكلفة والجودة لكن لم يصل لنقطة اتزان عملية.

---

## 8) القيود الصلبة (Hard Constraints)
1. الحساب حساس: أي submit سيء = مخاطرة عالية.
2. الميزانية: تم استهلاك >90$ بالفعل.
3. المطلوب مستقبلاً: نموذج واحد إن أمكن (لتقليل التكلفة).
4. بيئة VPS headless + ملفات حالة محلية + تحديثات متكررة.

---

## 9) المطلوب منك يا Claude Opus 4.6 (محدد وغير نظري)
### المطلوب الهندسي المباشر
1. إعادة تصميم البايبلاين بحيث يكون **Safety-first**.
2. تصميم حل يعمل فعليًا بنموذج واحد (Single-Model Mode) مع fallback policy واضحة عند الفشل.
3. تحويل المقارنة من “أفضل السيئين” إلى “قبول/رفض حتمي” مع repair loop.
4. تصميم validator دلالي أقوى (ليس قواعد نصية سطحية فقط).
5. ضمان deterministic pre-submit checks تمنع أي إرسال غير آمن.

### المطلوب على مستوى التنفيذ
1. خطة تغييرات ملف-بملف (patch plan واضح).
2. منطق state machine للحلقة:
   - Generate
   - Validate
   - Repair
   - Re-validate
   - Final gate
   - Manual fallback
3. حدود توقف واضحة:
   - عدد محاولات repair
   - متى نوقف تمامًا ونسلم للحكم اليدوي
4. خطة تقليل التكلفة:
   - نفس النموذج لكل المراحل إن أمكن
   - أو نموذج واحد + retry profile أقل تكلفة

---

## 10) مقترح معماري مبدئي (Draft Proposal)
### Phase 1: Stabilization
1. تفعيل strict gate دائمًا في production mode.
2. منع submit بالكامل إذا:
   - hallucination للفائز
   - submit_safe != winner
   - score < threshold
3. فرض `FORCE_REGENERATE` للحلقات الحرجة لمنع stale artifacts.

### Phase 2: Deterministic Repair Loop
1. candidate generation من نموذج واحد.
2. validator semantic + policy checks.
3. auto-repair prompt مبني على أخطاء validator (structured error-guided repair).
4. max attempts (مثلاً 2-3).
5. إذا فشل -> queue للحل اليدوي.

### Phase 3: Learning Loop
1. كل تصحيح يدوي يتحول إلى gold sample.
2. تجميع دوري few-shot/context bundle.
3. إعادة توليد Vertex cache/Context بشكل مجدول.
4. قياس التحسن أسبوعيًا بمؤشرات ثابتة.

---

## 11) مؤشرات الأداء المطلوبة (KPIs)
1. Submit-safe pass rate.
2. Hallucination rate.
3. Timestamp alignment error.
4. Repair success rate.
5. Cost per safe episode.
6. Episodes requiring manual intervention.

---

## 12) معايير قبول النسخة القادمة (Acceptance Criteria)
1. لا يوجد submit تلقائي مع أي mismatch أو hallucination.
2. تقارير واضحة لكل حلقة: لماذا قُبلت/رُفضت.
3. الوصول إلى معدل نجاح submit-safe متفق عليه على عينة اختبار داخلية.
4. خطة تشغيل واضحة بنموذج واحد (أو تبرير صارم لعدم إمكانية ذلك).

---

## 13) الملفات المرجعية التي يجب فحصها أولاً
1. `run_single_episode_4way.sh`
2. `atlas_triplet_batch.py`
3. `atlas_triplet_compare.py`
4. `atlas_web_auto_solver.py`
5. `sample_web_auto_solver.yaml`
6. `safe_update_preserve_local.sh`
7. `vertex_create_cache.py`
8. `atlas_build_vertex_fewshot.py`
9. `validator.py`
10. `repair_payload_builder.py`

---

## 14) الطلب النهائي الصريح
نحتاج منك خطة تنفيذ قوية تُخرج النظام من وضع:
“شغال تقنيًا لكن فاشل في 100% جودة”
إلى وضع:
“Production-safe، منخفض التكلفة، ويمكن الوثوق به في قرارات submit”.

**مهم جدًا:** لا تتعامل مع المشروع كتحسين برومبت فقط؛ اعتبره نظام قرار عالي المخاطرة يحتاج هندسة Reliability + Safety + Cost Control معًا.
