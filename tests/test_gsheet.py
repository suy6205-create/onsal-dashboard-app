import io

import pandas as pd
import pytest

from src import gsheet as G

CSV = """,,,,,
대시보드용 상품 정보,,,,,
SKU ID,품목,판매가,쿠팡 공급가,유통기한,회사 코드
81649500,비피다 세럼,"12,000","7,200",36개월,OA-0001
81231634,루메 로션,15000,9000,24개월,OA-0002
76911542,히알루론 세럼,9500,6435,,OA-0003
메모,,,,,
"""


def _raw(text=CSV):
    return pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)


def _master():
    return pd.DataFrame({"SKU ID": ["81649500", "76911542", "99999999"], "품목": ["비피다", "히알루론", "기타"],
                         "판매가": [10000.0, 9500.0, 0.0], "할인": [0.0] * 3, "원가": [0.0] * 3, "판매수수료율": [0.0, 0.3226, 0.0],
                         "운영중": ["Y"] * 3, "광고명키워드": [""] * 3, "브랜드": ["온살"] * 3, "회사코드": [""] * 3, "유통기한": [""] * 3})


def test_parse_sheet_url():
    u = "https://docs.google.com/spreadsheets/d/1AkwwToxnkg3V2Gx0ZMZXdebINtEtF5kG0EuhxJG7Z9g/edit?usp=sharing"
    assert G.parse_sheet_url(u) == ("1AkwwToxnkg3V2Gx0ZMZXdebINtEtF5kG0EuhxJG7Z9g", None)
    assert G.parse_sheet_url(u + "&gid=123")[1] == "123"
    assert G.csv_export_url(u).endswith("/export?format=csv")
    with pytest.raises(G.SheetError):
        G.parse_sheet_url("그냥 글자")


def test_header_detection_and_column_mapping():
    df, mp = G.read_table(_raw())
    assert mp == {"sku": "SKU ID", "name": "품목", "price": "판매가", "supply": "쿠팡 공급가", "shelf": "유통기한", "code": "회사 코드"}
    assert len(df) == 4                                            # 안내 줄(메모)은 아래 단계에서 걸러진다


def test_missing_sku_column_gives_friendly_error():
    with pytest.raises(G.SheetError, match="SKU ID"):
        G.read_table(_raw("a,b\n1,2\n"))


def test_updates_fee_rate_is_back_calculated_from_supply():
    df, mp = G.read_table(_raw())
    up = G.to_updates(df, mp).set_index("SKU ID")
    assert list(up.index) == ["81649500", "81231634", "76911542"]      # 숫자 SKU 만 (메모 줄 제외)
    assert up.loc["81649500", "판매가"] == 12000 and up.loc["81649500", "판매수수료율"] == pytest.approx(0.4)
    assert up.loc["76911542", "판매수수료율"] == pytest.approx(1 - 6435 / 9500, abs=1e-4)
    assert up.loc["81649500", "회사코드"] == "OA-0001" and up.loc["81649500", "유통기한"] == "36개월"


def test_diff_and_apply_only_touch_changed_nonempty_values():
    df, mp = G.read_table(_raw())
    up = G.to_updates(df, mp)
    diff = G.diff_with_master(up, _master())
    assert set(diff["SKU ID"]) == {"81649500", "76911542"}             # 마스터에 있는 SKU 만 (루메 로션은 마스터에 없음)
    assert ("76911542", "유통기한") not in set(zip(diff["SKU ID"], diff["칸"]))    # 시트 값이 비어 있으면 무시
    new, n = G.apply_updates(_master(), up)
    m = new.set_index("SKU ID")
    assert m.loc["81649500", "판매가"] == 12000 and m.loc["81649500", "회사코드"] == "OA-0001"
    assert m.loc["99999999", "판매가"] == 0.0 and m.loc["76911542", "유통기한"] == ""     # 건드리지 않음
    assert n >= 5 and G.apply_updates(new, up)[1] == 0                  # 두 번 적용해도 변화 없음


def test_item_name_is_not_overwritten_by_default_but_can_be():
    df, mp = G.read_table(_raw())
    up = G.to_updates(df, mp)
    assert "품목" not in set(G.diff_with_master(up, _master())["칸"])
    assert "품목" in set(G.diff_with_master(up, _master(), G.FIELDS)["칸"])
    assert G.apply_updates(_master(), up)[0].set_index("SKU ID").loc["81649500", "품목"] == "비피다"
    assert G.apply_updates(_master(), up, G.FIELDS)[0].set_index("SKU ID").loc["81649500", "품목"] == "비피다 세럼"
    d = G.diff_with_master(up, _master())
    assert all(isinstance(v, str) for v in d["현재(마스터)"]) and "원" in d.loc[d["칸"] == "판매가", "시트 값"].iloc[0]


# 실제 시트와 같은 모양(SKU ID 열 없음, 제품명으로 구분, 머리글에 줄바꿈, 유통기한에 날짜/X/빈칸) — 값은 모두 가짜
NAME_CSV = """,쿠팡 로켓,,,,,,,
,제품,판매가,"공급가
(V+)",원가,마진,마진율,유통기한,"(회사)
상품코드"
,테스트하이퍼비피다세럼,"9,000","  5,400 ","  3,000 ","  2,400 ",27%,2029-07-19,T0001
,테스트올인원로션   ,"12,900","  7,740 ","  3,600 ","  4,140 ",32%,X,T0002
,테스트시카세럼,"7,500","  4,500 ","  3,000 ","  1,500 ",20%,,T0002
,테스트롤러,"5,900","  3,500 ","  2,800 ",700,12%,2029-01-01,T0004
"""
NAMES = {"1001": ["테스트 하이퍼 비피다 세럼 30ml 1개", "비피다 세럼"],
         "1002": ["테스트 올인원 로션 150ml 1개"], "1003": ["테스트 시카 세럼 30ml"]}


def test_sheet_without_sku_column_matches_by_product_name():
    df, mp = G.read_table(_raw(NAME_CSV))
    assert set(mp) == {"name", "price", "supply", "cost", "shelf", "code"} and "sku" not in mp
    up = G.to_updates(df, mp, NAMES).set_index("SKU ID")
    assert list(up.index) == ["1001", "1002", "1003"]                     # 띄어쓰기가 달라도 연결
    assert up.loc["1001", "판매가"] == 9000 and up.loc["1001", "판매수수료율"] == pytest.approx(0.4)
    assert up.loc["1001", "원가"] == 3000 and up.loc["1002", "원가"] == 3600          # 원가 열도 가져온다
    assert up.loc["1002", "유통기한"] == "X" and up.loc["1003", "유통기한"] == "" and up.loc["1001", "회사코드"] == "T0001"
    assert up.attrs["unmatched"] == [("테스트롤러", "판매 데이터에 없는 제품")]


def test_name_match_edge_cases():
    names = {"1": ["온살 나이아신 10 세럼"], "2": ["온살 나이아신 20 세럼"]}
    assert G.match_by_name("온살나이아신10세럼", names) == ("1", "ok")        # 숫자가 다르면 다른 제품
    assert G.match_by_name("온살나이아신", names) == (None, "ambiguous")        # 여러 개에 걸리면 연결하지 않음
    assert G.match_by_name("전혀다른제품", names) == (None, "none") and G.match_by_name("", names) == (None, "none")
    with pytest.raises(G.SheetError):
        G.to_updates(*G.read_table(_raw(NAME_CSV)))                             # SKU 열이 없는데 이름 목록도 없으면 오류


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    from src import db
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    db.reset_engine()
    yield
    db.reset_engine()


def test_cost_is_part_of_diff_and_apply():
    df, mp = G.read_table(_raw(NAME_CSV))
    up = G.to_updates(df, mp, NAMES)
    m = _master().rename(columns={})
    m["SKU ID"] = ["1001", "1002", "1003"]
    m["품목"] = ["비피다", "로션", "시카"]
    d = G.diff_with_master(up, m)
    assert ("1001", "원가") in set(zip(d["SKU ID"], d["칸"]))
    new, n = G.apply_updates(m, up)
    assert new.set_index("SKU ID").loc["1001", "원가"] == 3000


def test_sheet_products_snapshot_prefills_new_sku_on_first_sale(tmpdb):
    """시트에 정리돼 있던 판매 전 제품이 처음 판매 데이터에 나오면, 가격·원가·유통기한·코드가 자동으로 채워진다."""
    import pandas as pd
    from src import config, service
    df, mp = G.read_table(_raw(NAME_CSV))
    snap = G.sheet_products(df, mp)
    assert len(snap) == 4 and "테스트롤러" in set(snap["시트제품명"])          # 연결 못 한 제품도 스냅샷에는 들어 있다
    config.save_sheet_products(snap)
    daily = pd.DataFrame({"sku_id": ["7001"], "sku_name": ["테스트 롤러 0.25mm 5개"], "brand": ["온살"]})
    assert service.add_new_skus_to_master(daily) == ["7001"]
    row = config.load_master().set_index("SKU ID").loc["7001"]
    assert (row["판매가"], row["원가"], row["회사코드"], row["유통기한"]) == (5900, 2800, "T0004", "2029-01-01")
    assert row["판매수수료율"] == pytest.approx(1 - 3500 / 5900, abs=1e-4)
    other = pd.DataFrame({"sku_id": ["7002"], "sku_name": ["시트에 없는 상품"], "brand": ["온살"]})
    service.add_new_skus_to_master(other)
    assert config.load_master().set_index("SKU ID").loc["7002", "판매가"] == 0       # 못 찾으면 예전처럼 가격 미입력
