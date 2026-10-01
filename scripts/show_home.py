"""홈 화면의 텍스트 결과(한 줄 요약·KPI·액션 리스트)를 터미널에 출력."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
for c in at.caption[:4]:
    print("·", c.value)
for i in at.info:
    print(i.value)
for w in at.warning:
    print("[경고]", w.value.replace("\n", " "))
print("--- KPI")
for m in at.metric:
    print(f"{m.label}: {m.value}  (Δ {m.delta})")
print("--- 액션 리스트")
for b in list(at.error) + list(at.warning) + list(at.success):
    if b.value.startswith("**"):
        print(b.value.replace("  \n", " | "))
