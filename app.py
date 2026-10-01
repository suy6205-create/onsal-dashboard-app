"""온살 판매·광고 통합 대시보드 진입점.  실행: streamlit run app.py
홈 화면은 pages/0_홈.py 에 있고, 여기서는 사이드바 메뉴(한국어 이름)만 구성한다."""
import streamlit as st

pg = st.navigation({
    "": [st.Page("pages/0_홈.py", title="홈 · 오늘의 요약", icon="🏠", default=True)],
    "🚀 로켓배송": [
        st.Page("pages/1_판매_재고.py", title="판매·재고", icon="📦"),
        st.Page("pages/2_로켓_광고_성과.py", title="로켓 광고 성과", icon="📢"),
        st.Page("pages/3_로켓_키워드_분석.py", title="로켓 키워드 분석", icon="🔑"),
        st.Page("pages/4_통합_손익.py", title="통합 손익", icon="💰"),
        st.Page("pages/5_체험단.py", title="체험단", icon="🎁"),
    ],
    "🪽 쿠팡윙": [
        st.Page("pages/2_윙_광고_성과.py", title="윙 광고 성과", icon="📢"),
        st.Page("pages/3_윙_키워드_분석.py", title="윙 키워드 분석", icon="🔑"),
    ],
    "설정": [st.Page("pages/9_데이터_업로드_설정.py", title="파일 업로드·설정", icon="📤")],
})
pg.run()
