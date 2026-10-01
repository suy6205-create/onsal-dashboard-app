"""모든 화면을 헤드리스로 한 번씩 실행해 예외가 없는지 확인한다.  python scripts/smoke_test.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from streamlit.testing.v1 import AppTest  # noqa: E402

pages = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "pages").glob("*.py"))
bad = 0
for pg in pages:
    target = "app.py" if pg.endswith("0_홈.py") else pg   # 홈은 메뉴(st.navigation)를 거쳐 실행
    at = AppTest.from_file(str(ROOT / target), default_timeout=60).run()
    errs = [e.value for e in at.exception]
    print(("OK  " if not errs else "FAIL"), pg, f"(info/warn/err 박스: {len(at.info)}/{len(at.warning)}/{len(at.error)})")
    for e in errs:
        bad += 1
        print("   ", e[:600])
sys.exit(1 if bad else 0)
