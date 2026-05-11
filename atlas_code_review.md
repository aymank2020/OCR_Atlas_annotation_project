# مراجعة محدثة لمشروع `OCR_annotation_Atlas`

تاريخ المراجعة: `2026-04-23`

هذه النسخة تحدّث التقرير السابق بناءً على الحالة الحالية داخل مساحة العمل المحلية نفسها، وليس على نسخة أقدم من GitHub فقط.

مهم:
- هذا التقرير يركز على مسار التشغيل الذي يحدد الوصول إلى `submit`.
- راجعت الملفات الحرجة فعليًا: `atlas_web_auto_solver.py`, `src/solver/legacy_impl.py`, `src/solver/orchestrator.py`, `src/solver/segments.py`, `src/solver/chat_only.py`, `src/solver/episode_runtime.py`, `src/solver/gemini_session.py`, `src/rules/policy_gate.py`, `src/rules/consistency.py`, `src/rules/labels.py`, `src/infra/artifacts.py`, `src/infra/browser_auth.py`, `config_account_danatimer_canary_v2.yaml`, `README.md`.
- لا أدّعي أني راجعت حرفيًا كل سطر من كل ملفات الريبو في جلسة واحدة. لكني راجعت خط التنفيذ الفعلي والملفات الأكثر تأثيرًا على الجودة والوصول إلى `submit`، مع مراجع سطرية واضحة.

---

## 1. الصورة الحقيقية الآن

### الحجم الفعلي

الحجم المحلي للمجلد الآن:

- `33.419 GB` إجمالي

أكبر مصادر الحجم:

| المسار | الحجم |
|---|---:|
| `outputs/` | `23.389 GB` |
| `.state/` | `3.716 GB` |
| `.venv/` | `2.559 GB` |
| `.git/` | `2.104 GB` |
| `discord/` | `1.097 GB` |
| `live_validation_update.bundle` | `212.5 MB` |
| `offline_packages/` | `158.5 MB` |
| `outputs_test/` | `38.9 MB` |

### حجم الكود نفسه أصغر بكثير من حجم المشروع الظاهر

- ملفات Python في الجذر: `81`
- ملفات Python داخل `src/`: `45`
- ملفات Python داخل `tests/`: `48`
- أسطر Python في الجذر: `37,664`
- أسطر Python في `src/`: `32,089`
- أسطر Python في `tests/`: `15,678`

هذا معناه أن المشكلة الأساسية لم تعد "حجم الكود فقط"، بل أن الريبو أصبح مساحة تشغيل كاملة تحتوي:

- بروفايلات متصفح
- نواتج فيديو
- صور وخطوات debug
- بيانات Discord
- بيئة افتراضية كاملة
- تاريخ Git ثقيل

### ملاحظة مهمة جدًا عن الحجم

`.state/chrome_user_data_link` ليس مجلدًا عاديًا. هو `Junction` إلى:

- `C:\Users\Ayman\AppData\Local\Google\Chrome\User Data`

وهذا وحده يظهر داخل المشروع بحجم يقارب:

- `19.2 GB`

إذًا جزء كبير من "حجم المشروع" الظاهر ليس من كود المشروع أصلًا، بل من ربط بروفايل كروم الحقيقي داخل الريبو.

---

## 2. مسار التشغيل الحقيقي الآن

### الحقيقة التنفيذية

ملف الدخول `atlas_web_auto_solver.py` لم يعد هو المنطق الحقيقي؛ هو shim فقط.

لكن الأهم:

- `src/solver/orchestrator.py:1793-1795`

```python
def run(cfg: Dict[str, Any], execute: bool) -> None:
    legacy = import_module("src.solver.legacy_impl")
    legacy.run(cfg, execute)
```

هذا يعني أن نقطة التشغيل الفعلية ما زالت ترجع إلى:

- `src/solver/legacy_impl.py`

أي أن refactor الوحدات الجديدة موجود جزئيًا، لكنه لم يصبح بعد المسار الرئيسي المستقل.

### تناقض في التوثيق

`README.md:53-56` يقول إن:

- `legacy_impl.py` "compatibility layer"
- وليس المصدر الأساسي للمسار النشط

لكن التنفيذ الحالي يثبت العكس: `legacy_impl.run(...)` ما زال هو قلب التشغيل الحقيقي.

هذه نقطة مهمة جدًا، لأن أي محاولة إصلاح "في المسار الجديد" وحده لن تكفي ما دام المسار الرئيسي ما زال يمر من `legacy_impl`.

---

## 3. أهم النتائج الحرجة

## [حرج جدًا] 1. مصدر الحقيقة للزمن ما زال غير منضبط بالكامل

هذه أهم نقطة مرتبطة مباشرة بسبب فشل الوصول إلى `submit`.

### أين المشكلة؟

في `src/rules/labels.py:1161-1177`:

```python
start_src = _safe_float(source.get("start_sec", 0.0), 0.0)
end_src = _safe_float(source.get("end_sec", 0.0), 0.0)
start_sec = _safe_float(item.get("start_sec", start_src), start_src)
end_sec = _safe_float(item.get("end_sec", end_src), end_src)
if end_sec <= start_sec:
    start_sec = start_src
    end_sec = end_src
max_drift = 12.0
if abs(start_sec - start_src) > max_drift:
    start_sec = start_src
if abs(end_sec - end_src) > max_drift:
    end_sec = end_src
```

المشكلة ليست في وجود clamp فقط، بل في أنه **متساهل جدًا**.

إذا كان DOM/source يقول:

- `5s`

وGemini رجّع:

- `15s`

فالفرق `10s` فقط، وهو أقل من `max_drift = 12.0`، وبالتالي الخطة ستحتفظ بزمن Gemini بدل زمن DOM.

### لماذا هذا خطير؟

لأن `AGENTS.md` يحدد بوضوح:

- DOM/source timestamps هي الحقيقة
- Gemini timestamps ليست authoritative

لكن هذا الجزء من الكود لا يطبق هذه القاعدة بشكل حاسم.

### النتيجة العملية

يمكن أن يتحول `segment_plan` إلى كائن يحمل زمنًا غير صحيح رغم أن `source_segments` نفسه صحيح.

وهنا تبدأ false rejections.

---

## [حرج جدًا] 2. الـ policy gate يعترف بالـ desync لكنه يستمر في الحظر

في `src/rules/policy_gate.py:185-201`:

```python
if plan_duration > max_segment_duration_sec + 0.05:
    errors.append(
        f"segment {idx}: duration {plan_duration:.1f}s exceeds max "
        f"{max_segment_duration_sec:.1f}s (MANDATORY SPLIT REQUIRED)"
    )

if (
    plan_duration > max_segment_duration_sec + 0.05
    and dom_duration <= max_segment_duration_sec + 0.05
):
    warnings.append(
        f"segment {idx}: DESYNC DETECTED - Gemini duration={plan_duration:.1f}s "
        f"but DOM duration={dom_duration:.1f}s (using DOM as ground truth)"
    )
    _logger.warning(
        "[policy] DESYNC segment %d: plan=%.1fs vs DOM=%.1fs - "
        "plan remains blocked despite DOM mismatch",
```

هذا السلوك متناقض منطقيًا:

- الكود يقول: "DOM هو الحقيقة الأرضية"
- ثم يضيف warning يعترف بالـ desync
- لكنه يبقي `error` الحاجب كما هو

### لماذا هذه أكبر مشكلة الآن؟

لأنها تفسر مباشرة العرض الذي وصفته في `AGENTS.md`:

- DOM يقول `5s`
- policy يقول `15s`

الكود الحالي لا يختار DOM عند التناقض، بل يذكر DOM ثم يحظر بناءً على plan.

### الحكم

هذا ليس تحسينًا تجميليًا. هذا bug منطقي في قلب مسار الجودة.

---

## [عالي جدًا] 3. المسار الرئيسي ما زال God-flow واحدًا داخل `legacy_impl.py`

أحجام الملفات الأساسية الآن:

| الملف | عدد الأسطر |
|---|---:|
| `src/solver/legacy_impl.py` | `7,384` |
| `src/solver/gemini.py` | `3,031` |
| `src/solver/segments.py` | `2,972` |
| `src/solver/gemini_session.py` | `1,950` |
| `src/solver/orchestrator.py` | `1,793` |
| `atlas_triplet_compare.py` | `5,543` |

النتيجة:

- tracing صعب
- ضمان invariants صعب
- config effects متداخلة
- الـ retry/repair/submit logic موزّع لكنه ما زال متشابك

وهذا يظهر أيضًا من أن:

- `legacy_impl.py` يستدعي `_finalize_current_episode_v2(...)` مرات كثيرة
- `_capture_episode_step(...)` يُستدعى `19` مرة داخل نفس الملف

أي أن عندنا كثافة orchestration عالية جدًا داخل ملف واحد.

---

## [عالي جدًا] 4. إعدادات YAML ليست دائمًا مصدر الحقيقة النهائي

في `src/solver/legacy_impl.py:5221-5249` توجد دالة:

- `_apply_global_run_policy(cfg)`

وفي `src/solver/legacy_impl.py:5299-5314`:

```python
cfg = _deep_merge(DEFAULT_CONFIG, raw)
...
_apply_global_gemini_video_policy(cfg)
_apply_global_run_policy(cfg)
```

هذه الدالة لا تستخدم `setdefault` فقط، بل تفرض قيمًا مباشرة، مثل:

- `skip_reserve_when_all_visible_blocked = False`
- `clear_blocked_tasks_every_retry = True`
- `reserve_cooldown_sec = 0`
- `release_and_reserve_on_all_visible_blocked = True`
- `release_and_reserve_on_submit_unverified = True`

### لماذا هذا خطر؟

لأن قراءة YAML وحدها لا تكفي لفهم السلوك الفعلي.

يعني لو config يقول قيمة، قد تتغيّر بعد التحميل داخل الكود نفسه.

وهذا يسبب:

- canary tuning غير متوقع
- صعوبة في reproducing المشاكل
- confusion أثناء debugging

---

## [عالي جدًا] 5. سياسة التنظيف الحالية لا تنظف أهم ما يستهلك المساحة

`src/infra/artifacts.py:26-35` يعرّف artifacts لكل task، ومنها:

- `video_<task>.mp4`
- `text_*`
- `segments_*`
- `labels_*`
- `prompt_*`
- `task_state_*`

لكن `src/infra/artifacts.py:180-220` في `_clear_episode_state(...)` يمسح فقط:

- labels cache
- segments cache
- labels dump
- prompt dump
- `_chat_only/<task>`

ولا يمسح:

- ملفات الفيديو
- `step_screenshots/`
- `episode_reports/`
- HTML/screenshot failure artifacts

### النتيجة

حتى مع وجود "clean state protocol" في:

- `src/solver/legacy_impl.py:6528-6539`

فإن التنظيف الحالي **لا يلمس أكبر الملفات أصلًا**.

---

## [عالي] 6. إعداد canary الحالي يولد artifacts كثيفة جدًا

في `config_account_danatimer_canary_v2.yaml:109-112`:

```yaml
use_task_scoped_artifacts: true
capture_step_screenshots: true
capture_step_screenshots_full_page: true
capture_step_html: true
```

ومع `src/infra/artifacts.py:348-384`:

- كل خطوة يمكن أن تكتب PNG
- ومعها HTML كامل للصفحة

وبما أن `_capture_episode_step(...)` مستخدم كثيرًا داخل `legacy_impl.py`، فإن canary الحالي مناسب للتحقيق العميق، لكنه **غير مناسب كإعداد دائم**.

دليل مباشر من نواتج التشغيل:

- `outputs/danatimer_canary_v2/step_screenshots` وحدها حوالي `177.3 MB`

وهذا فقط لمجلد ناتج واحد، بينما الأكبر عندك موجود في `outputs/training_feedback`.

---

## [عالي] 7. استخدام بروفايل كروم داخل الريبو هو أكبر سبب لتضخم `.state/`

### الحالة الحالية

في ملفات config/sample القديمة ما زال المسار:

- `AtlasAutoSolverConfig.yml:21`
- `sample_web_auto_solver.yaml`
- `sample_web_auto_solver_no_complete.yaml`

يشير إلى:

- `E:\OCR_annotation_Atlas\.state\chrome_user_data_link`

وهذا path هو Junction إلى بروفايل كروم الحقيقي.

وفي canary الفعلي:

- `config_account_danatimer_canary_v2.yaml` يستخدم `E:\OCR_annotation_Atlas\.state\gemini_chat_user_data`

وهو أيضًا داخل الريبو نفسه.

### لماذا هذا سيئ حتى لو كان ignored من git؟

لأنه يجعل مجلد المشروع نفسه يحتوي:

- profile caches
- extensions
- model stores
- service workers
- history/state

فتصبح مساحة العمل ضخمة، بطيئة، وصعبة النسخ أو الأرشفة.

---

## [متوسط-عال] 8. المشروع لم يعد "مشروع solver واحد" بل عدة منتجات داخل نفس الجذر

الجذر الآن فيه:

- `81` ملف Python
- `25` ملف YAML
- `50` ملف script (`.ps1/.sh/.bat`)
- `15` ملف Markdown
- `223` ملفًا في الجذر وحده

كما أن نفس المساحة تجمع بين:

1. solver الإنتاجي
2. chat-web stack
3. dashboards
4. Discord ingestion
5. WhatsApp/feedback exporters
6. command hub / control center
7. Colab packaging
8. study-pack / review docs / PDFs

هذا ليس مجرد "تنظيم سيئ"؛ هذا يرفع تكلفة أي debugging لأن حدود المنتج نفسه لم تعد واضحة.

---

## [متوسط] 9. `README.md` ما زال يعطي صورة غير مطابقة ويحتوي روابط مكسورة

في `README.md:54-56,96` الروابط كلها بصيغة:

- `/E:/OCR_annotation_Atlas/...`

وهذه روابط محلية مكسورة في GitHub.

كما أن الوصف المعماري نفسه لم يعد دقيقًا بخصوص دور `legacy_impl.py`.

---

## [متوسط] 10. ما زالت هناك نقاط تنفيذ shell خطرة في سكربتات الجذر

ما زال `shell=True` موجودًا في:

- `atlas_command_hub.py:98`
- `atlas_command_hub.py:108`
- `atlas_command_hub.py:149`
- `atlas_telegram_bot.py:52`
- `discord_updates_collector.py:198`
- `process_supervisor.py:107`
- `process_supervisor2.py:107`

هذه ليست في قلب submit path، لكنها تؤكد أن الجذر يحتوي tooling غير معزول وغير منظف.

---

## 4. ما الذي تحسن مقارنة بالتقرير السابق؟

ليس كل شيء أسوأ. هناك تطور حقيقي:

1. `.gitignore` الحالي صار يحتوي بالفعل على:
   - `outputs/`
   - `.state/`
   - `.venv/`
   - `discord/`

2. هناك فصل أفضل لبعض المكونات:
   - `episode_runtime.py`
   - `gemini_session.py`
   - `chat_only.py`
   - `desync.py`
   - `reliability.py`
   - `video_core.py`

3. يوجد pre-submit guard جيد في `src/solver/segments.py`:
   - `validate_pre_submit_consistency(...)`
   - `_pre_submit_duration_check(...)`

4. `chat_only.py` و `gemini_session.py` أضافا:
   - raw response persistence
   - baseline advancement checks
   - scope validation
   - schema validation

بمعنى آخر:

- طبقة الحماية الأخيرة قبل `submit` أفضل من قبل
- لكن الطريق المؤدي إليها ما زال معقدًا أكثر من اللازم

---

## 5. لماذا لا يصل النظام إلى `submit` بثبات؟

من مراجعة المسار الحالي، السبب الأساسي ليس "زر submit فقط".

السبب الحقيقي هو تفاعل هذه النقاط معًا:

1. `segment_plan` ما يزال يحتفظ أحيانًا بزمن Gemini بدل DOM.
2. `policy_gate` قد يحظر الحلقة على أساس plan حتى بعد الاعتراف بأن DOM مختلف.
3. `legacy_impl.run(...)` يحمل عدة modes ومسارات resume/retry/repair/requery في نفس التدفق.
4. config الفعلي ليس دائمًا هو ما هو مكتوب في YAML بسبب global policy overrides.
5. نواتج debug والـ state داخل نفس workspace تجعل الإشارات noisy جدًا.

بالتالي، قبل التفكير في "تحسين الجودة 100%"، يجب أولًا استعادة هذه invariant:

> أي قرار متعلق بالمدة والتقسيم يجب أن يُبنى على DOM/source فقط، لا على زمن Gemini.

---

## 6. أفضل مسار عملي للوصول إلى أعلى جودة ممكنة مع `submit` مستقر

لن أعدك بـ `100%` جودة حرفيًا، لأن النظام يعتمد على:

- UI حي
- DOM متغير
- متصفح
- LLM

لكن يمكن الوصول إلى:

- `100% fail-closed`
- ودرجة عالية جدًا من الثبات والجودة العملية قبل الإرسال

### المسار الموصى به

## المرحلة 1: تقليص المنتج إلى "Solver Core" فقط

هدف هذه المرحلة:

- جعل مساحة العمل تخدم هدفًا واحدًا: `extract -> plan -> validate -> apply -> submit`

المطلوب:

1. اعتبار هذه الوحدات فقط هي المنتج الأساسي:
   - `atlas_web_auto_solver.py`
   - `src/solver/*`
   - `src/rules/*`
   - `src/infra/*` المرتبطة بالsolver
   - `configs/*`
   - `tests/*` الخاصة بالsolver

2. نقل أو فصل ما يلي إلى مساحة مستقلة أو `extras/` أو repo منفصل:
   - `atlas_dashboard_gen.py`
   - `atlas_command_hub.py`
   - `atlas_control_center.py`
   - `atlas_feedback_training_export.py`
   - `atlas_discord_*`
   - `whatsapp_training_collector.py`
   - dashboards / reports / study-pack / PDFs

3. نقل generated episode configs من الجذر إلى:
   - `.state/generated_configs/`
   - أو `outputs/<account>/generated_configs/`

## المرحلة 2: فرض invariant الزمن بالقوة

هذا أهم تعديل منطقي في المشروع كله.

القاعدة المقترحة:

1. في أي labels-only pass:
   - `segment_plan.start_sec/end_sec` يجب أن تساوي `source_segments.start_sec/end_sec`
   - لا نسمح لـ Gemini بتعديل timestamps إطلاقًا

2. لا يُسمح بتغيير timeline إلا بعد:
   - structural op حقيقي
   - ثم `extract_segments(...)` جديد من DOM

3. إذا كان:
   - `plan_duration > max`
   - و `dom_duration <= max`

فهذا يجب أن يؤدي إلى أحد خيارين فقط:

- `re-extract / invalidate / re-query`
- أو overwrite لزمن الخطة بزمن DOM

وليس:

- policy block مباشر

## المرحلة 3: تثبيت مسار canary البسيط

للوصول إلى submit مستقر، أوصي بأن يكون canary المؤقت كالتالي:

1. `use_episode_runtime_v2: true`
2. `strict_single_chat_session: true`
3. `force_episode_browser_isolation: true`
4. `chat_only_mode: true`
5. `resume_from_artifacts: false`
6. `reuse_cached_labels: false`
7. `execute_force_live_segments: true`
8. `execute_force_fresh_gemini: true`
9. structural actions:
   - split فقط
   - بدون merge/delete حتى يثبت submit

الهدف:

- تقليل surface area
- منع replay لحالة قديمة
- منع تأثير cache على debugging

## المرحلة 4: تقليل output retention

الاحتفاظ الحالي مناسب للتحقيق، لكنه سيئ كتشغيل يومي.

المطلوب:

1. `capture_step_screenshots=false` في التشغيل العادي
2. `capture_step_html=false` في التشغيل العادي
3. تفعيل التصوير فقط:
   - عند failure
   - أو في canary one-episode

4. إضافة retention policy:
   - keep last `N=3` episode folders
   - حذف `video_*.mp4` القديمة
   - حذف `step_screenshots/` الأقدم من 3-7 أيام
   - حذف `_chat_only/` بعد النجاح

## المرحلة 5: اختبارات صغيرة على invariants بدل اختبارات ضخمة فقط

أهم 4 اختبارات يجب إضافتها فورًا:

1. `DOM=5s / Gemini=15s` يجب ألا يؤدي إلى policy block إذا لم تُطبق structural ops.
2. `labels-only response` يجب أن يرث timestamps من source دائمًا.
3. `policy_gate` عند desync يجب أن يطلب re-extract أو overwrite، لا block على زمن Gemini.
4. `artifact cleanup` يجب أن يزيل video/step artifacts القديمة وفق retention واضحة.

## المرحلة 6: rollout منضبط

الترتيب الصحيح:

1. 5 حلقات `dry-run`
2. 5 حلقات `apply without submit`
3. 5 حلقات `full submit canary`

بشرط أن يكون لكل حلقة:

- report موحد
- live DOM snapshot
- source snapshot
- final submit outcome

---

## 7. ما الذي يجب حذفه أو نقله الآن؟

### حذف آمن الآن إذا لم تكن تحتاجه للتحقيق الحالي

- `outputs/video_*.mp4` القديمة
- `outputs/*/step_screenshots/`
- `outputs/*/_chat_only/`
- `outputs_test/`
- `repomix-output.xml`
- `live_validation_update.bundle`
- ملفات PDFs والـ reports المولدة داخل الجذر إذا كانت مجرد مخرجات مراجعة
- `config_account_danatimer_canary_v2_episode_*.yaml`
- `config_account_danatimer_canary_v2_rescue.yaml` إذا انتهى استخدامها

### يجب نقلها خارج الريبو، لا مجرد حذفها

- `.venv/`
- `.state/gemini_chat_user_data`
- `.state/chrome_user_data_clone_*`
- `.state/chrome_user_data_danatimer`
- `.state/chrome_user_data_link` junction
- `discord/`
- `outputs/training_feedback/`

### يجب إبقاؤها

- `src/`
- `tests/`
- `configs/`
- `selectors.yaml`
- `run_gemini_chat_json.py`
- `atlas_triplet_compare.py`
- `AGENTS.md`

### ما زال يثقل Git نفسه ويجب مراجعته

الملفات tracked الكبيرة الحالية تشمل:

- `offline_packages/*.whl`
- `outputs_test/*.mp4`
- `data/f01.mp4`

وحجم `.git` الآن:

- `2.104 GB`

لذلك حتى بعد تنظيف workspace المحلي، قد تحتاج:

1. فصل الملفات الثنائية tracked
2. تنظيف التاريخ
3. أو إعادة clone نظيفة بعد أرشفة الضروري

---

## 8. ترتيب الأولويات الحقيقي الآن

### أولوية 1

أصلح هذه النقطة أولًا:

- اجعل timestamps في `segment_plan` دومًا من `source_segments` ما لم يحدث split/merge فعلي ثم re-extract

هذه النقطة وحدها أقرب شيء إلى "مفتاح الوصول إلى submit".

### أولوية 2

عدّل `policy_gate` ليعامل:

- `plan > max`
- `DOM <= max`

كحالة desync recovery، لا كحالة block نهائي.

### أولوية 3

خفف canary:

- بدون step screenshots full-page + html في كل خطوة
- بدون cache resume
- بدون outputs retention مفتوح

### أولوية 4

افصل المنتج:

- solver core
- ops/training/dashboard

### أولوية 5

أعد كتابة README والـ config story بحيث تطابق runtime الحقيقي.

---

## 9. الخلاصة التنفيذية

المشروع لا يفشل لأنه "كبير فقط".

هو يفشل في الوصول إلى `submit` بثبات لأن:

1. الحقيقة الزمنية ما زالت غير موحدة بالكامل
2. `policy_gate` لا يزال يحظر اعتمادًا على زمن Gemini في بعض حالات desync
3. المسار الفعلي ما زال يمر داخل `legacy_impl.run(...)`
4. الـ workspace متضخم ببيانات تشغيل وبروفايلات ومتعلقات ليست من جوهر المنتج

أفضل طريق للوصول إلى الهدف النهائي ليس إضافة ذكاء جديد، بل:

- تقليل المسارات
- توحيد مصدر الحقيقة
- جعل config قابلة للتنبؤ
- نقل state/artifacts خارج الريبو
- ثم تجربة canary بسيطة ونظيفة

إذا أردت التنفيذ العملي بعد هذا التقرير، فأفضل أول PR/تعديل فعلي هو:

1. إصلاح propagation للـ timestamps
2. تعديل behavior في `policy_gate` عند DOM/plan desync
3. إضافة اختبارين صغيرين يغلقان هذا bug نهائيًا

