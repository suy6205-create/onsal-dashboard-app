"""파일 파싱·정제. 화면/DB와 분리된 순수 함수들."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


class FileFormatError(ValueError):
    """업로드 파일 형식이 맞지 않을 때 (사용자에게 그대로 보여줄 메시지)."""


# ---------------------------------------------------------------- 공통 유틸
def clean_id(v) -> str:
    """95965222605.0 / 9.59e10 / ' 123 ' -> '95965222605'. 비어 있으면 ''."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    if s in ("", "nan", "None", "-"):
        return ""
    try:
        if re.fullmatch(r"-?\d+(\.0+)?", s):
            return str(int(float(s)))
        if re.fullmatch(r"-?\d+(\.\d+)?[eE][+-]?\d+", s):
            return str(int(float(s)))
    except ValueError:
        pass
    return s


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0)


def _norm(h) -> str:
    return re.sub(r"\s+", "", str(h))


def _iso(yyyymmdd: str) -> str:
    return datetime.strptime(yyyymmdd, "%Y%m%d").strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 판매 데이터
SALES_COLS = {
    "날짜": "date", "SKU ID": "sku_id", "SKU 명": "sku_name", "브랜드": "brand",
    "센터": "center", "바코드": "barcode", "발주가능상태": "orderable",
    "발주가능상태_세부": "orderable_detail", "입고수량": "inbound",
    "출고수량": "outbound", "현재재고수량": "stock", "매입원가": "supply_cost",
    "품절여부": "soldout",
}
SALES_FILE_RE = re.compile(r"basic_operation_rocket_(\d{8})(\d{8})")
DAILY_COLS = ["date", "sku_id", "sku_name", "barcode", "orderable", "orderable_detail",
              "inbound", "outbound", "stock", "supply_cost", "soldout"]


def parse_sales_filename(name: str) -> tuple[str, str] | None:
    """basic_operation_rocket_2026093020260930.csv -> ('2026-09-30','2026-09-30')"""
    m = SALES_FILE_RE.search(name)
    if not m:
        return None
    try:
        return _iso(m.group(1)), _iso(m.group(2))
    except ValueError:
        return None


@dataclass
class ParsedSales:
    center: pd.DataFrame                # 센터별 원본 (브랜드 필터 후)
    daily: pd.DataFrame                 # 날짜+SKU 합산
    total_rows: int = 0
    brand_rows: int = 0
    dates: list[str] = field(default_factory=list)


def aggregate_centers(center: pd.DataFrame) -> pd.DataFrame:
    """날짜+SKU 기준: 입고/출고/재고 합계, 품절은 하나라도 YES면 1, 나머지는 첫 값."""
    if center.empty:
        return pd.DataFrame(columns=DAILY_COLS)
    g = center.groupby(["date", "sku_id"], sort=True)
    out = g.agg(
        sku_name=("sku_name", "first"), barcode=("barcode", "first"),
        orderable=("orderable", "first"), orderable_detail=("orderable_detail", "first"),
        inbound=("inbound", "sum"), outbound=("outbound", "sum"), stock=("stock", "sum"),
        supply_cost=("supply_cost", "first"), soldout=("soldout", "max"),
    ).reset_index()
    return out[DAILY_COLS]


def normalize_sales_df(df: pd.DataFrame, brand: str) -> ParsedSales:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in SALES_COLS if c not in df.columns]
    if missing:
        raise FileFormatError(
            "로켓 판매 리포트가 아닌 것 같습니다. 없는 컬럼: " + ", ".join(missing))
    df = df.dropna(subset=["날짜"])
    total = len(df)
    df = df[df["브랜드"].astype(str).str.strip() == brand].copy()
    c = df[list(SALES_COLS)].rename(columns=SALES_COLS)
    c["date"] = pd.to_datetime(c["date"].apply(clean_id), format="%Y%m%d", errors="coerce")
    c = c.dropna(subset=["date"])
    c["date"] = c["date"].dt.strftime("%Y-%m-%d")
    c["sku_id"] = c["sku_id"].apply(clean_id)
    c["barcode"] = c["barcode"].apply(clean_id)
    for k in ("inbound", "outbound", "stock", "supply_cost"):
        c[k] = _num(c[k]).astype(int)
    c["soldout"] = (c["soldout"].astype(str).str.upper().str.strip() == "YES").astype(int)
    c["center"] = c["center"].astype(str)
    c = c.reset_index(drop=True)
    return ParsedSales(center=c, daily=aggregate_centers(c), total_rows=total,
                       brand_rows=len(c), dates=sorted(c["date"].unique()))


def parse_sales_csv(file, brand: str) -> ParsedSales:
    try:
        df = pd.read_csv(file, encoding="utf-8-sig", dtype={"바코드": str, "SKU ID": str})
    except Exception as e:  # noqa: BLE001
        raise FileFormatError(f"CSV를 읽을 수 없습니다: {e}") from e
    return normalize_sales_df(df, brand)


# ---------------------------------------------------------------- 광고 리포트
AD_BASE = {
    "과금방식": "billing", "판매방식": "sale_type", "광고유형": "ad_type",
    "캠페인ID": "campaign_id", "캠페인명": "campaign", "광고그룹": "ad_group",
    "광고집행상품명": "ad_product", "광고집행옵션ID": "ad_option_id",
    "광고전환매출발생상품명": "conv_product", "광고전환매출발생옵션ID": "conv_option_id",
    "광고노출지면": "placement", "키워드": "keyword", "노출수": "impressions",
    "클릭수": "clicks", "광고비": "cost",
}
_METRIC = {"주문수": "orders", "판매수량": "qty", "전환매출액": "rev"}
_KIND = {"총": "t", "직접": "d", "간접": "i"}
AD_CONV = {f"{k}{m}({w}일)": f"{_METRIC[m]}_{_KIND[k]}_{w}"
           for w in (1, 14) for k in _KIND for m in _METRIC}
AD_FILE_RE = re.compile(r"_(\d{8})_(\d{8})(?:\D|$)")
ID_COLS = ["광고집행 옵션ID", "광고전환매출발생 옵션ID", "캠페인 ID"]
AD_NUM_COLS = ["impressions", "clicks", "cost"] + list(AD_CONV.values())
AD_TEXT_COLS = ["billing", "sale_type", "ad_type", "campaign_id", "campaign", "ad_group",
                "ad_product", "ad_option_id", "conv_product", "conv_option_id", "placement",
                "keyword", "note", "placement_group"]
AD_DB_COLS = AD_TEXT_COLS + AD_NUM_COLS


def parse_ad_filename(name: str) -> tuple[str, str] | None:
    """A00000001_pa_total_campaign_20260921_20260927.xlsx -> ('2026-09-21','2026-09-27')"""
    m = AD_FILE_RE.search(name)
    if not m:
        return None
    try:
        s, e = _iso(m.group(1)), _iso(m.group(2))
    except ValueError:
        return None
    return (s, e) if s <= e else None


def placement_group(p: str) -> str:
    p = str(p)
    if "비검색" in p:
        return "비검색"
    if "외부" in p or "오디언스" in p:
        return "외부채널"
    return "검색"


def normalize_ad_df(df: pd.DataFrame) -> pd.DataFrame:
    """원본 광고 DataFrame -> DB용 영문 컬럼 DataFrame (비율 컬럼은 버림)."""
    ren: dict[str, str] = {}
    for h in df.columns:
        n = _norm(h)
        if n.startswith("판매방식"):
            n = "판매방식"
        elif n.startswith("광고노출지면"):
            n = "광고노출지면"
        if n in AD_BASE:
            ren[h] = AD_BASE[n]
        elif n in AD_CONV:
            ren[h] = AD_CONV[n]
        elif n == "비고":
            ren[h] = "note"
    have = set(ren.values())
    inv = {v: k for k, v in {**AD_BASE, **AD_CONV}.items()}
    missing = [inv[c] for c in list(AD_BASE.values()) + list(AD_CONV.values()) if c not in have]
    if missing:
        raise FileFormatError(
            "쿠팡 광고 리포트(캠페인 단위)가 아닌 것 같습니다. 없는 컬럼: " + ", ".join(missing))
    out = df.rename(columns=ren)
    out = out[[c for c in dict.fromkeys(ren.values())]].copy()
    if "note" not in out:
        out["note"] = ""
    for c in ("ad_option_id", "conv_option_id", "campaign_id"):
        out[c] = out[c].apply(clean_id)
    out["keyword"] = out["keyword"].fillna("-").astype(str).str.strip().replace({"": "-"})
    for c in AD_NUM_COLS:
        out[c] = _num(out[c])
    for c in ("sale_type", "ad_type", "campaign", "ad_group", "ad_product", "conv_product",
              "placement", "billing", "note"):
        out[c] = out[c].fillna("").astype(str).str.strip()
    out["placement_group"] = out["placement"].apply(placement_group)
    return out[AD_DB_COLS].reset_index(drop=True)


def parse_ad_xlsx(file) -> pd.DataFrame:
    try:
        df = pd.read_excel(file, dtype={c: str for c in ID_COLS})
    except Exception as e:  # noqa: BLE001
        raise FileFormatError(f"엑셀을 읽을 수 없습니다: {e}") from e
    return normalize_ad_df(df)


# ---------------------------------------------------------------- 광고 매핑 초안
def guess_bundle(name: str) -> int:
    """'온살 하이퍼 히알루론 수분 세럼,4개,4개,30ml,30ml' -> 4. 못 찾으면 1."""
    for p in [p.strip() for p in str(name).split(",")[1:]]:
        m = re.fullmatch(r"(\d+)\s*(개|입|팩|세트|EA|ea)", p)
        if m:
            return int(m.group(1))
    return 1


def draft_ad_map(ad: pd.DataFrame, master: pd.DataFrame, brand: str,
                 existing: pd.DataFrame | None = None) -> pd.DataFrame:
    """브랜드명이 들어간 옵션 중 매핑에 없는 것을 이름 규칙으로 추정해 초안 생성."""
    from .config import MAP_COLS
    known = set(existing["광고옵션ID"]) if existing is not None and len(existing) else set()
    rows: dict[str, dict] = {}
    for opt_col, name_col in (("ad_option_id", "ad_product"), ("conv_option_id", "conv_product")):
        sub = ad[[opt_col, name_col]].drop_duplicates()
        for oid, name in zip(sub[opt_col], sub[name_col]):
            if not oid or oid in known or oid in rows or brand not in str(name):
                continue
            sku = ""
            for _, m in master.iterrows():
                kw = str(m.get("광고명키워드", "") or "").strip()
                if kw and kw in str(name):
                    sku = str(m["SKU ID"])
                    break
            rows[oid] = {"광고옵션ID": oid, "광고상품명": name, "SKU ID": sku,
                         "묶음수량": guess_bundle(name),
                         "비고": "자동추정(확인 필요)" if sku else "SKU 미확정"}
    return pd.DataFrame(list(rows.values()), columns=MAP_COLS)


# ---------------------------------------------------------------- 레거시 이관
def read_legacy_workbook(path: str, brand: str):
    """쿠팡_로켓_판매재고_관리.xlsx -> (ParsedSales, 체험단 DataFrame)"""
    df = pd.read_excel(path, sheet_name="일일데이터", dtype={"바코드": str})
    df = df.drop(columns=[c for c in df.columns if str(c).startswith("일자")], errors="ignore")
    df = df.dropna(subset=["날짜"])
    parsed = normalize_sales_df(df, brand)

    raw = pd.read_excel(path, sheet_name="체험단", header=None)
    hdr = raw.index[raw.apply(lambda r: r.astype(str).str.contains("SKU ID").any(), axis=1)]
    trials = pd.DataFrame(columns=["date", "sku_id", "qty", "unit_price", "agency_fee", "memo"])
    if len(hdr):
        h = hdr[0]
        t = raw.iloc[h + 1:].copy()
        t.columns = [_norm(x) for x in raw.iloc[h]]
        t = t[pd.to_datetime(t["날짜"], errors="coerce").notna()]
        trials = pd.DataFrame({
            "date": pd.to_datetime(t["날짜"]).dt.strftime("%Y-%m-%d"),
            "sku_id": t["SKUID"].apply(clean_id),
            "qty": _num(t["체험단개수"]).astype(int),
            "unit_price": _num(t["제품가(공급가+VAT)"]),
            "agency_fee": 0.0,
            "memo": t["업체/메모"].fillna("").astype(str) if "업체/메모" in t else "",
        }).reset_index(drop=True)
    return parsed, trials
