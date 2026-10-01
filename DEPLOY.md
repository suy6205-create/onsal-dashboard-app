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
APP_PASSWORD = "대시보드에 접속할 때 쓸 비밀번호"
```

4. **Deploy** → 몇 분 뒤 `https://앱이름.streamlit.app` 주소가 생깁니다.

## 5단계. 접속 제한 (권장)

- 앱의 **Share** 에서 "이 앱을 볼 수 있는 사람"을 **특정 이메일만** 으로 설정하세요.
- 위 `APP_PASSWORD` 를 설정했다면 접속할 때 비밀번호도 한 번 더 묻습니다 (이중 보호).
  비밀번호가 필요 없으면 APP_PASSWORD 줄을 빼면 됩니다.

---

## 평소 사용

- 접속: 발급된 `streamlit.app` 주소 (휴대폰 포함 어디서든)
- 매일: 📤 파일 업로드 → 저장 (데이터가 Neon 에 쌓입니다)
- 코드를 고쳤을 때: `git push` 하면 자동으로 다시 배포됩니다.
- 며칠 안 쓰면 앱이 잠듭니다 → 주소를 열면 "Wake up" 버튼이 나오고 약 30초 뒤 켜집니다. (무료 플랜 특성)

## 주의

- **로컬과 온라인은 데이터가 따로입니다.** 로컬 `실행.bat` 은 로컬 DB, 온라인은 Neon DB 를 씁니다.
  온라인으로 옮긴 뒤에는 온라인 쪽에만 업로드하는 것을 권장합니다.
- 백업: 온라인 화면의 `파일 업로드·설정 → 내보내기` 에서 전체 엑셀을 내려받을 수 있습니다. 주 1회 권장.
- 로컬 PC 에서 온라인 DB 의 엑셀 백업을 받으려면 `$env:DATABASE_URL` 설정 후 `python scripts/backup.py`.
- Neon 무료 플랜은 용량 0.5GB 입니다. 광고 한 달치가 약 8천 행이므로 수년간 충분합니다.
