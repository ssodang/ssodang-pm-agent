# ssodang-pm-agent

쏘댕 in BUSAN PM 에이전트. Notion 개발 논의 안건 DB를 매일 조회해서 마감 임박/기한 초과 안건을 슬랙으로 알림.

GitHub Actions Cron으로 매일 20:14 KST에 자동 실행. 별도 서버 없음, 인프라 비용 0원.

## 셋업

### 1. 필요한 비밀값

| 변수 | 설명 | 받는 곳 |
|---|---|---|
| `NOTION_TOKEN` | Notion Integration 토큰 | https://www.notion.so/profile/integrations |
| `NOTION_AGENDA_DB_ID` | 개발 논의 안건 DB ID | DB URL의 32자리 UUID |
| `NOTION_CALENDAR_DB_ID` | 회의 일정 캘린더 DB ID | DB URL의 32자리 UUID |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL | https://api.slack.com/apps |

### 2. GitHub Secrets 등록

레포 **Settings → Secrets and variables → Actions → New repository secret** 에서 위 4개 등록.

### 3. Notion Integration을 DB에 초대

DB 페이지 우상단 `···` → `Connections` → `ssodang-pm-agent` 선택.

### 4. 동작 확인

- 자동: 매일 20:14 KST
- 수동: **Actions 탭 → PM Agent Daily → Run workflow**

## 로컬 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env 파일에 값 채우기

export $(grep -v '^#' .env | xargs)
python pm_agent.py
```

## 알림 기준

조회 대상: 상태가 `완료`가 아닌 안건

- 🔴 **기한 초과**: 마감일이 오늘 이전
- 🟡 **마감 임박**: 마감일이 2일 이내

알릴 안건이 하나도 없으면 슬랙으로 메시지 안 보냄 (스팸 방지).

## 알림 예시

```
📋 확인 필요한 개발 논의 안건

🔴 기한 초과 (1건)
  • 디자인 스펙 논의 (마감 05/28, 🟡 논의 전)

🟡 마감 임박 (2건, 2일 이내)
  • API 스키마 구조 (마감 05/29, 🔵 논의 중)
  • 인증 방식 결정 (마감 05/30, 🟡 논의 전)
```

## 변경 가능한 설정

`pm_agent.py` 상단의 `IMMINENT_DAYS` 값으로 "임박" 기준 조절 (기본 2일).
