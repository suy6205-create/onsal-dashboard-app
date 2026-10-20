"""적재 로직 (업로드 화면·이관 스크립트 공용): DB 저장 + 마스터/매핑표 자동 갱신."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import config, db
from .loaders import ParsedSales, classify_ad_period, draft_ad_map


def add_new_skus_to_master(daily: pd.DataFrame) -> list[str]:
    """판매데이터에 처음 나온 SKU 를 마스터에 자동 추가(가격 0 = '가격 미입력' 경고 대상)."""
    master = config.load_master()
    known = set(master["SKU ID"])
    new = []
    rows = []
    for sku, name, brand in daily[["sku_id", "sku_name", "brand"]].drop_duplicates("sku_id").itertuples(index=False):
        if sku not in known:
            new.append(sku)
            rows.append({"SKU ID": sku, "품목": name, "판매가": 0, "할인": 0, "원가": 0,
                         "판매수수료율": 0, "운영중": "Y", "광고명키워드": "", "브랜드": brand, "회사코드": "", "유통기한": ""})
    if rows:
        config.save_master(pd.concat([master, pd.DataFrame(rows)], ignore_index=True))
    return new


def new_skus(daily: pd.DataFrame) -> list[str]:
    known = set(config.load_master()["SKU ID"])
    return [s for s in daily["sku_id"].unique() if s not in known]


def ingest_sales(parsed: ParsedSales, filename: str = "") -> list[str]:
    db.upsert_sales(parsed.center, parsed.daily, filename)
    return add_new_skus_to_master(parsed.daily)


@dataclass
class AdIngest:
    status: str                    # saved | skipped | rejected
    kind: str | None = None        # 일 | 주
    message: str = ""
    replace: list = field(default_factory=list)   # 주 파일이 대체하는 일 단위 기간들
    n_draft: int = 0


def plan_ad_ingest(start: str, end: str, periods: pd.DataFrame) -> AdIngest:
    """광고 파일 기간이 저장 규칙에 맞는지 판단한다 (저장하지 않는 순수 함수 — 미리보기에서도 사용).
    규칙: 일(하루)·주(월~일)만 저장. 주 파일은 그 주 안의 일 데이터를 대체. 이미 주 파일이 있는 날짜의 일 파일은 건너뜀."""
    kind = classify_ad_period(start, end)
    if kind is None:
        return AdIngest("rejected", None, f"기간 {start}~{end} 은(는) 하루(일 단위)도, 월요일~일요일(주 단위)도 아닙니다. "
                        "월간·임의 구간 파일은 데이터가 겹쳐서 저장하지 않습니다. 쿠팡 광고 리포트를 '하루' 또는 '월~일 한 주'로 다시 내려받아 올려주세요.")
    spans = [(r.period_start, r.period_end) for r in periods.itertuples()] if len(periods) else []
    if kind == "주":
        inside = [sp for sp in spans if sp[0] >= start and sp[1] <= end and sp != (start, end)]
        msg = f"이 주 안에 저장돼 있던 일 단위 데이터 {len(inside)}건을 주 단위로 대체합니다." if inside else ""
        return AdIngest("saved", kind, msg, inside)
    weekly = [sp for sp in spans if classify_ad_period(*sp) == "주" and sp[0] <= start and sp[1] >= end]
    if weekly:
        w = weekly[0]
        return AdIngest("skipped", kind, f"{start} 은(는) 이미 주 단위 파일({w[0]}~{w[1]})에 들어 있어서 일 단위로는 저장하지 않았습니다. "
                        "일 단위로 바꾸려면 파일 업로드·설정 → 광고 데이터 관리에서 그 주 파일을 먼저 삭제하세요.")
    return AdIngest("saved", kind)


def ingest_ad(ad: pd.DataFrame, start: str, end: str, filename: str = "", brand="온살") -> AdIngest:
    """광고 저장(규칙 적용) + 매핑표 초안 자동 생성(기존 매핑은 보존)."""
    plan = plan_ad_ingest(start, end, db.ad_periods())
    if plan.status != "saved":
        return plan
    if plan.replace:
        db.delete_ad_periods(plan.replace)
    db.upsert_ad(ad, start, end, filename)
    existing = config.load_map()
    draft = draft_ad_map(ad, config.load_master(), brand, existing)
    if len(draft):
        config.save_map(pd.concat([existing, draft], ignore_index=True))
    plan.n_draft = len(draft)
    return plan
