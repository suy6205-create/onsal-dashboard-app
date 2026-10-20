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
