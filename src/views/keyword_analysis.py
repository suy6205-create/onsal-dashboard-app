"""로켓/윙 공용 키워드 분석 화면. render(code, label, icon)"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src import actions
from src import metrics as M
from src import ui


def render(code: str, label: str, icon: str) -> None:
    cfg = ui.setup(f"{label} 키워드 분석", icon)
    cfg = ui.type_cfg(cfg, code)
    d = ui.load_all(cfg)
    f = ui.ad_filters(d, cfg, f"kw_{code}", fixed_stype=label)
    if f is None:
        st.stop()
    p = f["df"]
    kw = actions.keyword_table(p, cfg)
    if kw.empty:
        st.info("검색 영역 키워드 데이터가 없습니다.")
        st.stop()

    waste, share = actions.wasted_cost_share(kw)
    n_ex = int((kw["분류"] == "제외 후보").sum())
    ui.headline([f"검색 광고비의 {share*100:.0f}%(₩{waste:,.0f})가 전환 0건 키워드에서 발생 — 제외 후보 {n_ex}개"
                 if waste > 0 else "전환 없이 광고비만 쓴 키워드가 없습니다."])
    st.caption("키워드는 '검색 영역' 행만 사용합니다(비검색·외부채널은 키워드가 '-'). "
               f"분류 기준: 제외 후보=광고비 ₩{cfg['exclude_min_cost']:,} 이상 & 주문 0, 데이터 부족=클릭 {cfg['min_clicks']} 미만 "
               "(로켓/윙 기준값은 '📤 파일 업로드·설정' → 기준값 탭에서 따로 변경)")

    t_tbl, t_quad, t_cls, t_grp = st.tabs(["키워드 테이블", "4분면 산점도", "자동 분류", "키워드 그룹 비교"])

    fmt = {"cost": st.column_config.NumberColumn("광고비", format="₩%d"), "cpc": st.column_config.NumberColumn("CPC", format="₩%d"),
           "cpa": st.column_config.NumberColumn("CPA", format="₩%d", help="광고비 ÷ 주문수"),
           "ctr": st.column_config.NumberColumn("CTR", format="percent"), "cvr": st.column_config.NumberColumn("CVR", format="percent"),
           "roas": st.column_config.NumberColumn("ROAS", format="percent", help="전환매출액 ÷ 광고비"),
           "be_roas": st.column_config.NumberColumn(ui.ref_label(f["stype"]), format="percent"),
           "rev": st.column_config.NumberColumn("전환매출", format="₩%d"), "keyword": "키워드",
           "impressions": "노출", "clicks": "클릭", "orders": "주문"}
    cols = ["keyword", "분류", "impressions", "clicks", "ctr", "cpc", "cost", "orders", "cvr", "rev", "roas", "cpa", "be_roas"]

    with t_tbl:
        q = st.text_input("키워드 검색", "")
        t = kw[kw["keyword"].str.contains(q, case=False, regex=False)] if q else kw
        st.dataframe(t.sort_values("cost", ascending=False)[cols], hide_index=True, width="stretch", column_config=fmt)

    with t_quad:
        k2 = kw[(kw["cost"] > 0)].copy()
        if k2.empty:
            st.info("광고비가 발생한 키워드가 없습니다.")
        else:
            split = float(k2["cost"].median())
            be = M.safe_div((k2["be_roas"] * k2["cost"]).sum(), k2["cost"].sum(), cfg["default_breakeven_roas"])
            k2["사분면"] = [M.quadrant(c, r, be, split) for c, r in zip(k2["cost"], k2["roas"])]
            colors = {"핵심 유지": "#54A24B", "확대": "#4C78A8", "축소·제외": "#E45756", "관찰": "#9D9D9D"}
            fig = go.Figure()
            for qn, g in k2.groupby("사분면"):
                fig.add_scatter(x=g["cost"], y=g["roas"] * 100, mode="markers", name=qn, text=g["keyword"],
                                marker=dict(color=colors[qn], size=(g["clicks"].clip(lower=1) ** 0.5 * 6).clip(8, 50), opacity=.7),
                                customdata=g[["clicks", "orders", "impressions"]].values,
                                hovertemplate="<b>%{text}</b><br>광고비 ₩%{x:,.0f}<br>ROAS %{y:.0f}%<br>클릭 %{customdata[0]:.0f} · 주문 %{customdata[1]:.0f}<extra></extra>")
            fig.add_hline(y=be * 100, line_dash="dash", line_color="#E45756",
                          annotation_text=f"{ui.ref_label(f['stype'])} {be*100:.0f}%", annotation_position="top left")
            fig.add_vline(x=split, line_dash="dot", line_color="#999",
                          annotation_text=f"광고비 중앙값 ₩{split:,.0f}", annotation_position="bottom right")
            fig.update_layout(xaxis_title="광고비(₩)", yaxis_title="ROAS(%)")
            ui.show(fig, 480)
            st.caption("우상=돈 쓰고 잘 팔림(핵심 유지) · 좌상=적게 쓰고 잘 팖(확대) · 우하=돈 쓰고 안 팔림(축소·제외) · 좌하=관찰. "
                       "버블 크기=클릭수. 광고비 구분선은 중앙값입니다.")

    with t_cls:
        order = ["효자", "제외 후보", "입찰 상향 후보", "데이터 부족", "관찰/개선"]
        tabs = st.tabs([f"{n} ({int((kw['분류'] == n).sum())})" for n in order])
        desc = {"효자": "ROAS가 기준(로켓=손익분기, 윙=목표) 이상 — 유지", "제외 후보": "광고비를 쓰고도 주문 0건 — 제외 키워드로 등록 검토",
                "입찰 상향 후보": "ROAS 양호 & 노출 적음 — 입찰가를 올려 노출 확대", "데이터 부족": "클릭이 적어 판단 보류",
                "관찰/개선": "ROAS가 기준 미만 — 입찰 하향·상품 구성 점검"}
        for tb, n in zip(tabs, order):
            with tb:
                st.caption(desc[n])
                t = kw[kw["분류"] == n].sort_values("cost", ascending=False)
                st.dataframe(t[cols], hide_index=True, width="stretch", column_config=fmt)
                if n == "제외 후보" and len(t):
                    st.markdown("**제외 키워드 후보 목록** (우측 상단 복사 버튼)")
                    st.code("\n".join(t["keyword"]), language=None)
                    st.download_button("⬇️ CSV 다운로드", t[["keyword", "cost", "clicks"]].to_csv(index=False).encode("utf-8-sig"),
                                       file_name="제외키워드후보.csv", mime="text/csv")

    with t_grp:
        s = p[p["placement_group"] == "검색"].copy()
        tags = s["keyword"].apply(lambda x: M.keyword_group_tags(x, cfg.get("keyword_groups", {}), cfg["brand"]))
        for dim in ("브랜드", "언어", "상품군"):
            s[dim] = [t[dim] for t in tags]
        dim = st.radio("묶는 기준", ["브랜드", "언어", "상품군"], horizontal=True,
                       help="브랜드=키워드에 브랜드명 포함 여부 · 언어=한글/영문 · 상품군=설정의 키워드 그룹 규칙")
        g = M.ad_summary(s, [dim])
        st.dataframe(g[[dim, "impressions", "clicks", "cost", "orders", "rev", "ctr", "cpc", "cvr", "roas", "cpa"]],
                     hide_index=True, width="stretch", column_config=fmt)
        fig = go.Figure(go.Bar(x=g[dim], y=g["roas"] * 100, marker_color="#4C78A8", customdata=g[["cost", "orders"]].values,
                               hovertemplate="%{x}<br>ROAS %{y:.0f}%<br>광고비 ₩%{customdata[0]:,.0f} · 주문 %{customdata[1]:.0f}<extra></extra>"))
        fig.update_layout(yaxis_title="ROAS(%)", title=f"{dim}별 ROAS")
        ui.show(fig, 320)
