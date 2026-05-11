# Quickstart: 4-Way Episode Solver Pipeline

## المتطلبات

### 1. Python Dependencies
```bash
pip install playwright requests pyyaml google-auth google-generativeai
playwright install chromium
```

### 2. System Dependencies
- **ffmpeg**: لضغط الفيديو → `sudo apt install ffmpeg`
- **rclone**: لتحميل من Google Drive (اختياري)

### 3. ملف الإعدادات
نسخ الـ template وتعديل المتغيرات:
```bash
cp sample_web_auto_solver.yaml web_auto_solver.yaml
```

### 4. متغيرات البيئة
```bash
# .env file
GEMINI_API_KEY=<your-gemini-api-key>
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GOOGLE_CLOUD_PROJECT=<your-gcp-project>
```

## التشغيل السريع

### حل حلقة واحدة (4-way)
```bash
EPISODE_ID=<episode-id> \
VIDEO_FILE=/path/to/video.mp4 \
bash run_single_episode_4way.sh
```

### تشغيل batch
```bash
python atlas_triplet_batch.py \
  --config web_auto_solver.yaml \
  --index /path/to/episodes/index.jsonl
```

### فحص الأمان يدويًا
```bash
python submit_gate.py \
  --result-json outputs/triplet_compare_<eid>.json \
  --min-pass-score 95
```

### تشغيل repair loop
```bash
python -c "
from atlas_repair_loop import run_repair_loop
from pathlib import Path
result = run_repair_loop(
    episode_id='<eid>',
    segments=[...],
    config_path='web_auto_solver.yaml',
    outputs_dir=Path('outputs'),
    min_pass_score=95,
)
print(result.to_dict())
"
```

## التحقق من نجاح الحل

1. `quality_pass=True` في الـ output
2. `score_pct ≥ 95`
3. `hallucination=False` لكل المرشحين
4. `submit_safe_solution == winner`

## الملفات الناتجة

```
outputs/
├── triplet_compare_<eid>.json  # نتيجة المقارنة
├── manual_queue.jsonl           # حلقات تحتاج حل يدوي
├── repair_history.jsonl         # سجل محاولات الإصلاح
├── repaired/                    # حلول مُصلحة
└── gemini_usage.jsonl           # تتبع التكلفة
```
