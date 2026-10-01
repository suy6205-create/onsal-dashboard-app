"""규칙 기반 '오늘의 액션 리스트'와 한 줄 요약(인사이트 문장) 생성."""
from __future__ import annotations

import pandas as pd

from . import metrics as M

LEVEL_ORDER = {"🔴": 0, "🟡": 1, "🟢": 2}


def keyword_table(ad_p: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """검색 영역 키워드별 집계 + 자동 분류. ad_p 는 metrics.prep_ad 결과."""
    s = ad_p[ad_p["placement_group"] == "검색"]
    if s.empty:
        return pd.DataFrame()
    kw = M.ad_summary(s, ["keyword"])
    return M.classify_keywords(kw, cfg)


def wasted_cost_share(kw: pd.DataFrame) -> tuple[float, float]:
    """(전환 0건 키워드 광고비, 비중)."""
    if kw.empty or kw["cost"].sum() == 0:
        return 0.0, 0.0
    w = float(kw.loc[kw["orders"] == 0, "cost"].sum())
    return w, w / float(kw["cost"].sum())


def build_actions(sku_tbl: pd.DataFrame, ad_p: pd.DataFrame, cfg: dict) -> list[dict]:
    acts: list[dict] = []
    red, drop = cfg["stock_red_days"], cfg["drop_pct"] / 100

    for _, r in sku_tbl[sku_tbl["운영중"]].iterrows():
        if r["품절"]:
            acts.append(dict(level="🔴", key=0, title=f"품절 발생: {r['품목']}",
                             detail=f"품절 상태입니다. 발주 권장 {r['발주권장']:,}개"))
        elif not r["발주가능"]:
            acts.append(dict(level="🔴", key=0, title=f"발주 불가 상태: {r['품목']}",
                             detail=f"발주가능상태 = '{r['발주가능상태']}' (현재재고 {r['현재재고']:,}개)"))
        dl = r["소진예상일"]
        if dl is not None and not pd.isna(dl) and dl <= red:
            acts.append(dict(level="🔴", key=1, title=f"발주 필요: {r['품목']}",
                             detail=f"재고 {r['현재재고']:,}개 · 소진까지 약 {dl:.0f}일 — 권장 {r['발주권장']:,}개"))
        ch = r["7일평균_증감"]
        if ch is not None and not pd.isna(ch) and r["직전7일평균"] > 0 and ch <= -drop:
            acts.append(dict(level="🟡", key=5, title=f"판매 급감: {r['품목']}",
                             detail=f"7일평균 {r['7일평균']:.1f}개/일, 직전 7일({r['직전7일평균']:.1f}) 대비 {ch*100:.0f}%"))

    if len(ad_p):
        kw = keyword_table(ad_p, cfg)
        if len(kw):
            ex = kw[kw["분류"] == "제외 후보"].sort_values("cost", ascending=False)
            if len(ex):
                top = ", ".join(f"{k}(₩{c:,.0f})" for k, c in zip(ex["keyword"].head(3), ex["cost"].head(3)))
                acts.append(dict(level="🟡", key=2, title=f"제외 키워드 후보 {len(ex)}개",
                                 detail=f"광고비 ₩{ex['cost'].sum():,.0f} 소진, 주문 0건 — {top}"))
            up = kw[kw["분류"] == "입찰 상향 후보"].sort_values("roas", ascending=False)
            if len(up):
                top = ", ".join(f"{k}(ROAS {r:.1f}배)" for k, r in zip(up["keyword"].head(3), up["roas"].head(3)))
                acts.append(dict(level="🟢", key=6, title=f"입찰가 상향 후보 {len(up)}개",
                                 detail=f"ROAS 양호·노출 적음 — {top}"))
        # 손익분기 미만 상품
        prod = M.ad_summary(ad_p, ["ad_product"])
        bad = prod[(prod["cost"] > 0) & (prod["roas"] < prod["be_roas"])].sort_values("cost", ascending=False)
        if len(bad):
            tot = M.ad_summary(ad_p)
            top = ", ".join(f"{n.split(',')[0]} {n.split(',')[1] if ',' in n else ''}".strip() for n in bad["ad_product"].head(2))
            acts.append(dict(level="🟡", key=3, title=f"손익분기 ROAS 미만 광고 상품 {len(bad)}개",
                             detail=f"전체 ROAS {tot['roas'].iloc[0]:.2f}배 (손익분기 약 {tot['be_roas'].iloc[0]:.1f}배) — {top} 등"))
    acts.sort(key=lambda a: (LEVEL_ORDER[a["level"]], a["key"]))
    return acts


def build_headline(sku_tbl: pd.DataFrame, ad_p: pd.DataFrame, cfg: dict) -> list[str]:
    """화면 상단 한 줄 요약 문장들."""
    out = []
    t = sku_tbl[sku_tbl["운영중"] & sku_tbl["소진예상일"].notna()].sort_values("소진예상일")
    if len(t):
        r = t.iloc[0]
        if r["소진예상일"] <= cfg["stock_yellow_days"]:
            out.append(f"{r['품목']} 재고 소진까지 {r['소진예상일']:.0f}일 — 발주 필요 (권장 {r['발주권장']:,}개)")
    if len(ad_p):
        kw = keyword_table(ad_p, cfg)
        w, share = wasted_cost_share(kw)
        if share >= 0.1:
            out.append(f"이번 광고비의 {share*100:.0f}%(₩{w:,.0f})가 전환 0건 키워드에서 발생")
        tot = M.ad_summary(ad_p).iloc[0]
        if tot["cost"] > 0 and tot["roas"] < tot["be_roas"]:
            out.append(f"광고 ROAS {tot['roas']:.2f}배로 손익분기({tot['be_roas']:.1f}배) 미만 — 광고 구조 점검 필요")
    if not out:
        out.append("긴급한 이슈가 없습니다. 아래 액션 리스트를 확인하세요.")
    return out
