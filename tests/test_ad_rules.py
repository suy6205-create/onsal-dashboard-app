import pandas as pd
import pytest

from src import db, service
from src import loaders as L


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    db.reset_engine()
    yield
    db.reset_engine()


def _ad(rows=2):
    d = {c: ["x"] * rows for c in L.AD_TEXT_COLS} | {c: [1.0] * rows for c in L.AD_NUM_COLS}
    d["sale_type"] = ["Retail"] * rows
    return pd.DataFrame(d)


def test_classify_ad_period():
    assert L.classify_ad_period("2026-10-15", "2026-10-15") == "일"
    assert L.classify_ad_period("2026-10-12", "2026-10-18") == "주"          # 월~일
    assert L.classify_ad_period("2026-10-13", "2026-10-19") is None          # 화~월 7일은 주 단위가 아님
    assert L.classify_ad_period("2026-10-01", "2026-10-05") is None          # 임의 구간
    assert L.classify_ad_period("2026-09-01", "2026-09-30") is None          # 월간


def test_rejects_monthly_and_arbitrary_ranges(tmpdb):
    r = service.ingest_ad(_ad(), "2026-09-01", "2026-09-30", "m.xlsx")
    assert r.status == "rejected" and "월~일" in r.message
    assert db.read_ad().empty


def test_daily_then_weekly_replaces_the_days(tmpdb):
    for day in ("2026-10-12", "2026-10-13", "2026-10-14"):
        assert service.ingest_ad(_ad(), day, day, f"{day}.xlsx").status == "saved"
    assert len(db.ad_periods()) == 3
    r = service.ingest_ad(_ad(3), "2026-10-12", "2026-10-18", "w.xlsx")
    assert r.status == "saved" and len(r.replace) == 3
    per = db.ad_periods()
    assert list(zip(per.period_start, per.period_end)) == [("2026-10-12", "2026-10-18")]


def test_daily_inside_existing_week_is_skipped(tmpdb):
    service.ingest_ad(_ad(), "2026-10-12", "2026-10-18", "w.xlsx")
    r = service.ingest_ad(_ad(), "2026-10-14", "2026-10-14", "d.xlsx")
    assert r.status == "skipped" and "주 단위 파일" in r.message
    assert len(db.ad_periods()) == 1
    r2 = service.ingest_ad(_ad(), "2026-10-19", "2026-10-19", "d2.xlsx")   # 다음 주 첫날은 저장
    assert r2.status == "saved"


def test_same_period_again_overwrites(tmpdb):
    service.ingest_ad(_ad(2), "2026-10-14", "2026-10-14", "a.xlsx")
    service.ingest_ad(_ad(5), "2026-10-14", "2026-10-14", "b.xlsx")
    assert len(db.read_ad()) == 5


def test_delete_ad_periods_and_all(tmpdb):
    service.ingest_ad(_ad(), "2026-10-14", "2026-10-14", "a.xlsx")
    service.ingest_ad(_ad(), "2026-10-15", "2026-10-15", "b.xlsx")
    db.delete_ad_periods([("2026-10-14", "2026-10-14")])
    assert list(db.ad_periods().period_start) == ["2026-10-15"]
    db.delete_all_ad()
    assert db.read_ad().empty


def test_non_retail_rows_are_dropped_on_normalize():
    raw = {}
    for header, key in {**L.AD_BASE, **L.AD_CONV}.items():
        raw[header] = ["Retail", "3P"] if key == "sale_type" else [1, 1]
    # 컬럼명은 원본 리포트 형태(공백 포함 가능)와 같아야 하므로 정규화 전 헤더를 그대로 사용
    df = pd.DataFrame(raw)
    out = L.normalize_ad_df(df)
    assert list(out["sale_type"]) == ["Retail"] and out.attrs["dropped_non_retail"] == 1


def _p(spans):
    rows = []
    for s, e in spans:
        r = {"period_start": s, "period_end": e, "cost": 100.0}
        rows.append(r)
    return pd.DataFrame(rows)


def test_tag_and_weekly_frame_counts_each_week_once():
    from src import metrics as M
    p = _p([("2026-09-01", "2026-09-30"),                       # 월간: 규칙 밖 -> 제외
            ("2026-10-05", "2026-10-11"),                       # 주 파일
            ("2026-10-07", "2026-10-07"),                       # 같은 주의 일 데이터 -> 주 파일이 우선
            ("2026-10-12", "2026-10-12"), ("2026-10-13", "2026-10-13")])   # 진행 중인 주
    t = M.tag_ad_periods(p)
    assert set(t["kind"]) == {"주", "일"} and len(t) == 4
    wf = M.ad_weekly_frame(t)
    assert sorted(zip(wf["week"], wf["kind"])) == [("2026-10-05", "주"), ("2026-10-12", "일"), ("2026-10-12", "일")]
    assert dict(zip(wf["week"], wf["n_days"])) == {"2026-10-05": 7, "2026-10-12": 2}


def test_ad_coverage_strip():
    from src import metrics as M
    t = M.tag_ad_periods(_p([("2026-10-05", "2026-10-11"), ("2026-10-12", "2026-10-12")]))
    cov = M.ad_coverage(t, today="2026-10-14", weeks=3).set_index("week")
    assert cov.loc["2026-10-05", "주 단위 파일"] == "✅" and cov.loc["2026-10-12", "일 단위 파일"] == 1
    assert cov.loc["2026-09-28", "주 단위 파일"] == "—"
