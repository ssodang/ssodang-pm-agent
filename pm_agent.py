"""
ssodang PM Agent

매일 20:14 KST에 GitHub Actions Cron으로 실행.

알림 내용:
  - 오늘 〈회의〉 태그 일정이 있으면 헤더 + @channel 호출
  - 마감 임박/기한 초과한 개발 논의 안건 알림
"""

import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from notion_client import Client


# ─────────── 환경변수 ───────────

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_AGENDA_DB_ID = os.environ.get("NOTION_AGENDA_DB_ID")
NOTION_CALENDAR_DB_ID = os.environ.get("NOTION_CALENDAR_DB_ID")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# 임박 기준 (일)
IMMINENT_DAYS = 2

# 미팅으로 인정할 태그
MEETING_TAG = "회의"

# GitHub Actions runner는 UTC라서 날짜 판단은 명시적으로 KST 기준으로 한다.
KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(KST).date()


def query_all_database_pages(notion: Client, db_id: str, **kwargs) -> list[dict]:
    results = []
    start_cursor = None

    while True:
        response = notion.databases.query(
            database_id=db_id,
            page_size=100,
            start_cursor=start_cursor,
            **kwargs,
        )
        results.extend(response["results"])

        if not response.get("has_more"):
            return results

        start_cursor = response.get("next_cursor")


# ─────────── Notion: 캘린더에서 오늘 미팅 조회 ───────────

def fetch_today_meetings(notion: Client, db_id: str) -> list[dict]:
    """캘린더 DB에서 오늘 날짜에 걸리는 '회의' 태그 일정 조회."""
    today = today_kst()

    pages = query_all_database_pages(
        notion,
        db_id,
        filter={
            "and": [
                {
                    "property": "태그",
                    "multi_select": {"contains": MEETING_TAG},
                },
                {
                    "property": "기간",
                    "date": {"is_not_empty": True},
                },
            ]
        },
        sorts=[{"property": "기간", "direction": "ascending"}],
    )

    meetings = []
    for page in pages:
        props = page["properties"]

        # 제목
        title_prop = props.get("제목", {}).get("title", [])
        title = title_prop[0]["plain_text"] if title_prop else "(제목 없음)"

        # 기간 (오늘 포함 여부 재확인 — API 필터의 한계 보완)
        date_info = props.get("기간", {}).get("date") or {}
        start_str = (date_info.get("start") or "")[:10]
        end_str = (date_info.get("end") or start_str)[:10]
        if not start_str:
            continue

        start_d = date.fromisoformat(start_str)
        end_d = date.fromisoformat(end_str) if end_str else start_d
        if not (start_d <= today <= end_d):
            continue

        meetings.append({
            "title": title,
            "url": page["url"],
        })

    return meetings


# ─────────── Notion: 안건 조회 ───────────

def fetch_agenda_items(notion: Client, db_id: str) -> list[dict]:
    pages = query_all_database_pages(
        notion,
        db_id,
        filter={
            "property": "상태",
            "select": {"does_not_equal": "완료"},
        },
        sorts=[{"property": "마감일", "direction": "ascending"}],
    )

    items = []
    for page in pages:
        props = page["properties"]

        title_prop = props.get("안건", {}).get("title", [])
        title = title_prop[0]["plain_text"] if title_prop else "(제목 없음)"

        due_prop = props.get("마감일", {}).get("date")
        due_date = None
        if due_prop and due_prop.get("start"):
            due_date = date.fromisoformat(due_prop["start"])

        status_prop = props.get("상태", {}).get("select")
        status = status_prop["name"] if status_prop else "(미지정)"

        items.append({
            "title": title,
            "due_date": due_date,
            "status": status,
            "url": page["url"],
        })

    return items


# ─────────── 분류 ───────────

def classify_items(items: list[dict]) -> dict[str, list[dict]]:
    today = today_kst()
    imminent_cutoff = today + timedelta(days=IMMINENT_DAYS)

    overdue = []
    imminent = []

    for item in items:
        if not item["due_date"]:
            continue
        if item["due_date"] < today:
            overdue.append(item)
        elif item["due_date"] <= imminent_cutoff:
            imminent.append(item)

    return {"overdue": overdue, "imminent": imminent}


# ─────────── 메시지 포맷 ───────────

STATUS_EMOJI = {
    "논의 전": "🟡",
    "논의 중": "🔵",
    "완료": "🟢",
}


def format_agenda(item: dict) -> str:
    emoji = STATUS_EMOJI.get(item["status"], "⚪")
    due_str = item["due_date"].strftime("%m/%d") if item["due_date"] else "미정"
    return f"  • <{item['url']}|{item['title']}> (마감 {due_str}, {emoji} {item['status']})"


def build_message(meetings: list[dict], classified: dict[str, list[dict]]) -> str | None:
    overdue = classified["overdue"]
    imminent = classified["imminent"]
    has_meetings = len(meetings) > 0
    has_agenda = len(overdue) > 0 or len(imminent) > 0

    if not has_meetings and not has_agenda:
        return None

    lines = []

    # 미팅 섹션
    if has_meetings:
        today_str = today_kst().strftime("%Y.%m.%d")
        lines.append(f"*[{today_str} 정기 미팅 스레드]*")
        lines.append("<!channel>")
        lines.append("")
        lines.append("📅 *오늘의 회의*")
        for m in meetings:
            lines.append(f"  • <{m['url']}|{m['title']}>")
        lines.append("")

    # 안건 섹션
    if has_agenda:
        if has_meetings:
            lines.append("────────────────")
            lines.append("")
        lines.append("📋 *확인 필요한 개발 논의 안건*")
        lines.append("")

        if overdue:
            lines.append(f"🔴 *기한 초과* ({len(overdue)}건)")
            lines.extend(format_agenda(item) for item in overdue)
            lines.append("")

        if imminent:
            lines.append(f"🟡 *마감 임박* ({len(imminent)}건, {IMMINENT_DAYS}일 이내)")
            lines.extend(format_agenda(item) for item in imminent)

    return "\n".join(lines).strip()


# ─────────── Slack 전송 ───────────

def send_to_slack(webhook_url: str, message: str) -> None:
    response = httpx.post(
        webhook_url,
        json={"text": message, "link_names": 1},
        timeout=10.0,
    )
    response.raise_for_status()


# ─────────── 메인 ───────────

def main() -> int:
    missing = [name for name, value in {
        "NOTION_TOKEN": NOTION_TOKEN,
        "NOTION_AGENDA_DB_ID": NOTION_AGENDA_DB_ID,
        "NOTION_CALENDAR_DB_ID": NOTION_CALENDAR_DB_ID,
        "SLACK_WEBHOOK_URL": SLACK_WEBHOOK_URL,
    }.items() if not value]

    if missing:
        print(f"❌ 환경변수 누락: {', '.join(missing)}", file=sys.stderr)
        return 1

    notion = Client(auth=NOTION_TOKEN)

    # 캘린더 — 오늘 회의 조회
    try:
        meetings = fetch_today_meetings(notion, NOTION_CALENDAR_DB_ID)
        print(f"📅 오늘 회의: {len(meetings)}건")
    except Exception as e:
        print(f"❌ 캘린더 조회 실패: {e}", file=sys.stderr)
        return 1

    # 안건 조회
    try:
        items = fetch_agenda_items(notion, NOTION_AGENDA_DB_ID)
    except Exception as e:
        print(f"❌ 안건 조회 실패: {e}", file=sys.stderr)
        return 1

    classified = classify_items(items)
    print(f"📊 안건: 총 {len(items)}건 / 기한 초과 {len(classified['overdue'])} / 임박 {len(classified['imminent'])}")

    # 메시지 조립
    message = build_message(meetings, classified)
    if not message:
        print("✅ 알릴 거 없음. 종료.")
        return 0

    # 슬랙 전송
    try:
        send_to_slack(SLACK_WEBHOOK_URL, message)
        print("✅ 슬랙 알림 발송 완료")
    except Exception as e:
        print(f"❌ 슬랙 전송 실패: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
