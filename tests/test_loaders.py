import io

import pandas as pd
import pytest

from src import loaders as L
from src.loaders import FileFormatError


def _sales_df(rows):
    cols = ["날짜", "상품 카테고리", "하위 카테고리", "세부 카테고리", "브랜드", "센터", "SKU ID", "SKU 명",
            "바코드", "발주가능상태", "발주가능상태_세부", "입고수량", "출고수량", "현재재고수량", "매입원가",
            "발주대비 납품율", "확정대비 납품율", "회송율", "회송사유", "품절여부", "세부카테고리 품절율"]
    base = dict(zip(cols, [20260930, "B", "S", "D", "온살", "VF107", 1, "A", "8800000000001", "발주가능", "정상",
                           0, 0, 0, 6000, 0, 0, 0, None, "NO", 0.7]))
    return pd.DataFrame([{**base, **r} for r in rows])


def test_center_aggregation():
    df = _sales_df([
        {"센터": "VF107", "출고수량": 3, "현재재고수량": 10, "입고수량": 5, "품절여부": "NO"},
        {"센터": "FC", "출고수량": 2, "현재재고수량": 4, "입고수량": 0, "품절여부": "YES"},
        {"브랜드": "타사", "출고수량": 99},
    ])
    p = L.normalize_sales_df(df, "온살")
    assert p.total_rows == 3 and p.brand_rows == 2 and len(p.center) == 2
    r = p.daily.iloc[0]
    assert (r["outbound"], r["stock"], r["inbound"], r["soldout"]) == (5, 14, 5, 1)
    assert r["date"] == "2026-09-30"


def test_sales_missing_columns_message():
    df = _sales_df([{}]).drop(columns=["출고수량", "매입원가"])
    with pytest.raises(FileFormatError) as e:
        L.normalize_sales_df(df, "온살")
    assert "출고수량" in str(e.value) and "매입원가" in str(e.value)


def test_barcode_stays_string():
    csv = ("날짜,브랜드,센터,SKU ID,SKU 명,바코드,발주가능상태,발주가능상태_세부,입고수량,출고수량,현재재고수량,매입원가,품절여부\n"
           "20260930,온살,VF107,1,a,8800000000001,발주가능,정상,0,1,5,100,NO\n")
    p = L.parse_sales_csv(io.StringIO(csv), "온살")
    assert p.daily.iloc[0]["barcode"] == "8800000000001"


def test_filename_dates():
    assert L.parse_ad_filename("A00000001_pa_total_campaign_20260921_20260927.xlsx") == ("2026-09-21", "2026-09-27")
    assert L.parse_ad_filename("A1_pa_total_campaign_20260930_20260930 (1).xlsx") == ("2026-09-30", "2026-09-30")
    assert L.parse_ad_filename("report.xlsx") is None
    assert L.parse_ad_filename("x_20260931_20260930.xlsx") is None
    assert L.parse_sales_filename("basic_operation_rocket_2026093020260930 (1).csv") == ("2026-09-30", "2026-09-30")
    assert L.parse_sales_filename("basic_operation_rocket_2026080120260910.csv") == ("2026-08-01", "2026-09-10")


def test_clean_id():
    assert L.clean_id("95965222605.0") == "95965222605"
    assert L.clean_id(95965222605.0) == "95965222605"
    assert L.clean_id(float("nan")) == ""
    assert L.clean_id("-") == ""


def test_guess_bundle():
    assert L.guess_bundle("온살 하이퍼 히알루론 수분 세럼,4개,4개,30ml,30ml") == 4
    assert L.guess_bundle("온살 540 mts 더마 롤러 0.25mm,5개,5개,무색,무색") == 5
    assert L.guess_bundle("온살 뭔가") == 1


def test_ad_missing_columns_message():
    with pytest.raises(FileFormatError) as e:
        L.normalize_ad_df(pd.DataFrame({"캠페인명": ["a"], "광고비": [1]}))
    assert "키워드" in str(e.value)
