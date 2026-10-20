"""화면·모듈이 부르는 함수가 실제로 존재하는지 정적으로 점검한다.
(함수를 실수로 지우거나 이름을 바꿨을 때, 그 코드 경로를 실행해 보기 전에는 모르고 지나가는 오류를 막는다)"""
import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ALIAS = {"service": "src.service", "config": "src.config", "db": "src.db", "ui": "src.ui", "M": "src.metrics",
         "gsheet": "src.gsheet", "L": "src.loaders", "actions": "src.actions"}
FILES = [ROOT / "app.py", *sorted((ROOT / "pages").glob("*.py")), *sorted((ROOT / "src").rglob("*.py")), *sorted((ROOT / "scripts").glob("*.py"))]
PAT = re.compile(r"(?<![\w.])(" + "|".join(ALIAS) + r")\.([A-Za-z_]\w*)")


def _used():
    found = {}
    for f in FILES:
        text = f.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            for mod, attr in PAT.findall(line):
                found.setdefault((mod, attr), set()).add(f.name)
    return found


@pytest.mark.parametrize("mod,attr,files", [(m, a, sorted(f)) for (m, a), f in sorted(_used().items())])
def test_referenced_attribute_exists(mod, attr, files):
    module = importlib.import_module(ALIAS[mod])
    assert hasattr(module, attr), f"{ALIAS[mod]}.{attr} 가 없습니다 (사용처: {', '.join(files)})"
