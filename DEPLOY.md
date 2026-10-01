# 온라인 배포 가이드 (무료)

구성: **GitHub 비공개 저장소 → Streamlit Community Cloud(앱 실행) + Neon(무료 Postgres, 데이터 저장)**
데이터는 Neon DB 에 저장되므로 앱이 잠들거나 재시작돼도 사라지지 않습니다.
로컬에서 `실행.bat` 으로 쓰는 방식은 그대로 동작합니다 (DATABASE_URL 이 없으면 로컬 SQLite 사용).

총 소요: 약 30분. 모든 서비스 무료 플랜으로 충분합니다.

---

## 1단계. 온라인 DB 만들기 (Neon)

1. https://neon.tech 가입 (GitHub 계정으로 로그인 가능)
2. **Create project** → 이름 `onsal`, 지역은 가까운 곳(예: Singapore) 선택
3. 대시보드의 **Connection string** 을 복사합니다. 이런 모양입니다.
   `postgresql://사용자:비밀번호@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
   - 이 주소는 **비밀번호가 들어 있으니 남에게 보이거나 GitHub 에 올리면 안 됩니다.**

## 2단계. 로컬 데이터를 온라인 DB 로 옮기기 (1회)

PowerShell 에서:

```powershell
cd C:\Users\OA\Desktop\쿠팡대시보드
$env:DATABASE_URL = "여기에 1단계에서 복사한 주소"
python scripts/copy_to_cloud.py
```

`sales_daily: 56행 복사` 같은 줄이 나오고 `완료` 가 뜨면 성공입니다.

## 3단계. GitHub 비공개 저장소에 올리기

1. https://github.com/new → 이름 `onsal-dashboard`, **Private(비공개)** 선택 → 생성
2. PowerShell 에서 (주소는 본인 것으로):

```powershell
cd C:\Users\OA\Desktop\쿠팡대시보드
git remote add origin https://github.com/내아이디/onsal-dashboard.git
git push -u origin master
```

`data/`, `backups/`, `sample_data/` 는 `.gitignore` 로 제외되어 있어 영업 데이터는 올라가지 않습니다.
(저장소에는 `config/` 의 초기 마스터·매핑 파일만 올라갑니다. 실제 값은 DB 에 저장됩니다.)

## 4단계. Streamlit Community Cloud 에 배포

1. https://share.streamlit.io 에서 GitHub 로그인
2. **Create app** → 저장소 `onsal-dashboard`, 브랜치 `master`, Main file path `app.py`
3. **Advanced settings**
   - Python version: **3.12 또는 3.13**
   - **Secrets** 칸에 아래를 붙여넣기 (값은 본인 것으로):

```toml
DATABASE_URL = "postgresql://사용자:비밀번호@ep-xxxx.neon.tech/neondb?sslmode=require"
ADMIN_PASSWORD = "업로드·설정·등록에 쓸 관리자 비밀번호"
```

4. **Deploy** → 몇 분 뒤 `https://앱이름.streamlit.app` 주소가 생깁니다.

## 5단계. 권한 구조 (보기 / 관리)

- **보기**: 비밀번호 없이 누구나 (주소를 아는 사람) 모든 분석 화면을 볼 수 있습니다.
- **관리** (파일 업로드·설정 화면, 체험단 등록·수정): 왼쪽 메뉴 아래 **관리자 로그인**에 비밀번호를 입력해야 합니다.
- 관리자 비밀번호는 Secrets 의 `ADMIN_PASSWORD` (없으면 `APP_PASSWORD`) 값입니다. 둘 다 없으면 누구나 관리 기능을 쓸 수 있으니 반드시 설정하세요.
- 보기도 제한하고 싶으면 앱 **Settings → Sharing** 에서 특정 이메일만 허용하세요.
- 주의: 보기 화면에는 광고비·매출·원가 기반 수치(순이익 등)가 나옵니다. 주소는 믿을 수 있는 사람에게만 공유하세요.

