#!/usr/bin/env bash
# Temporary script for testing the Timestamp Fix & GCS Update

echo "──────────────────────────────────────────────────────"
echo " [1] سحب أحدث التعديلات من جيت هاب بأمان (دون المساس بالمفاتيح)"
echo "──────────────────────────────────────────────────────"
# Using git stash just in case there are local uncommitted changes that might block pull
git stash > /dev/null 2>&1 || true
git fetch origin feature/phase1-hardening
git checkout feature/phase1-hardening
git pull origin feature/phase1-hardening

echo ""
echo "──────────────────────────────────────────────────────"
echo " [2] تفعيل البيئة الوهمية"
echo "──────────────────────────────────────────────────────"
if [[ -f ".venv/bin/activate" ]]; then
  source .venv/bin/activate
  echo "✔ تم تفعيل البيئة الوهمية."
else
  echo "⚠️ لم يتم العثور على البيئة الوهمية .venv"
fi

echo ""
echo "──────────────────────────────────────────────────────"
echo " [3] تشغيل حلقة واحدة تجريبية (Dry-run) للتأكد من حل الأخطاء"
echo "──────────────────────────────────────────────────────"
python atlas_web_auto_solver.py \
  --config sample_web_auto_solver_production.yaml \
  --max-episodes 1

echo ""
echo "──────────────────────────────────────────────────────"
echo " ✔ تم الانتهاء! راجع النتائج أعلاه وتأكد من اختفاء أخطاء الـ Timestamps."
echo " بانتظار ردك لحذف هذا السكربت المؤقت واعتماد الحلقة بـ --execute."
echo "──────────────────────────────────────────────────────"
