import argparse
import datetime
import html
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple

BASE_DIR = pathlib.Path(__file__).resolve().parent
PROMPT_FILE = BASE_DIR / "ai_prompt.txt"
DOCS_DIR = BASE_DIR / "docs"
EXTERNAL_ENV_FILE = pathlib.Path(r"D:\FinanceData\kakao_stock_news.env")

REPORT_WEB_URL = "https://thehojunlee.github.io/kakao-stock-news/"

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def load_local_env() -> None:
    """볼트 외부(D:\\FinanceData\\kakao_stock_news.env)에 저장된 환경변수가 있으면 불러옵니다."""
    if not EXTERNAL_ENV_FILE.exists():
        return
    for line in EXTERNAL_ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v and k not in os.environ:
            os.environ[k] = v


def http_post_form(
    url: str, form_data: Dict[str, str], headers: Dict[str, str] | None = None
) -> Dict:
    """표준 라이브러리(urllib)만으로 x-www-form-urlencoded POST 요청을 보냅니다."""
    encoded_data = urllib.parse.urlencode(form_data).encode("utf-8")
    req_headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=encoded_data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} 오류 ({url}): {err_body}") from e


def http_post_json(
    url: str, payload: Dict, headers: Dict[str, str] | None = None
) -> Dict:
    """표준 라이브러리(urllib)만으로 application/json POST 요청을 보냅니다."""
    encoded_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json; charset=utf-8",
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=encoded_data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} 오류 ({url}): {err_body}") from e


def clean_headline(raw_title: str, max_len: int = 90) -> str:
    """언론사 접미사 제거 및 깔끔한 한 줄 제목으로 정리합니다."""
    title = html.unescape(raw_title).strip()
    if " - " in title:
        title = title.rsplit(" - ", 1)[0].strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) > max_len:
        title = title[: max_len - 1].rstrip() + "…"
    return title


def fetch_rss_items(rss_url: str, source_label: str, limit: int = 5) -> List[str]:
    """지정된 RSS URL에서 최신 뉴스 제목 목록을 가져옵니다."""
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
        results = []
        seen = set()
        for item in root.findall("./channel/item"):
            raw_title = item.findtext("title") or ""
            cleaned = clean_headline(raw_title)
            if not cleaned:
                continue
            prefix = re.sub(r"[^\w가-힣]", "", cleaned.lower())[:14]
            if prefix in seen:
                continue
            seen.add(prefix)
            results.append(f"[{source_label}] {cleaned}")
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        print(f"[경고] {source_label} 수집 중 오류 발생 (건너뜀): {e}", file=sys.stderr)
        return []


def fetch_google_news_rss(query: str, source_label: str, limit: int = 5) -> List[str]:
    """구글 뉴스 한국어 RSS에서 검색어 기준 최신 뉴스를 가져옵니다."""
    encoded_query = urllib.parse.quote(query)
    rss_url = (
        f"https://news.google.com/rss/search?q={encoded_query}"
        f"&hl=ko&gl=KR&ceid=KR:ko"
    )
    return fetch_rss_items(rss_url, source_label=source_label, limit=limit)


def fetch_naver_securities_news(limit: int = 8) -> Tuple[List[str], List[str]]:
    """네이버 증권 속보/주요뉴스 섹션에서 미국 증시 및 국내 증시 기사를 분류해 가져옵니다."""
    url = "https://news.naver.com/breakingnews/section/101/258"
    us_list: List[str] = []
    kr_list: List[str] = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")

        titles = re.findall(r'class="sa_text_strong">([^<]+)</strong>', raw_html)
        us_keywords = (
            "뉴욕",
            "나스닥",
            "S&P",
            "다우",
            "미 증시",
            "미국증시",
            "월가",
            "연준",
            "Fed",
            "엔비디아",
            "테슬라",
        )
        seen = set()
        for t in titles:
            cleaned = clean_headline(t)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            if any(k in cleaned for k in us_keywords):
                if len(us_list) < limit:
                    us_list.append(f"[네이버증권] {cleaned}")
            else:
                if len(kr_list) < limit:
                    kr_list.append(f"[네이버증권] {cleaned}")
    except Exception as e:
        print(f"[경고] 네이버 증권 뉴스 수집 중 오류 발생 (건너뜀): {e}", file=sys.stderr)

    return us_list, kr_list


def collect_all_sources() -> Tuple[List[str], List[str]]:
    """4대 뉴스 소스(네이버 증권, 구글 뉴스, 인베스팅닷컴, 야후 파이낸스)를 종합 수집합니다."""
    naver_us, naver_kr = fetch_naver_securities_news(limit=5)

    google_us = fetch_google_news_rss(
        "뉴욕증시 OR 미국증시 OR 나스닥 마감 when:1d", source_label="구글뉴스", limit=5
    )
    google_kr = fetch_google_news_rss(
        "코스피 시황 OR 국내증시 OR 장마감 시황 OR 출발 시황 when:1d",
        source_label="구글뉴스",
        limit=5,
    )

    investing_all = fetch_rss_items(
        "https://kr.investing.com/rss/news_25.rss", source_label="인베스팅닷컴", limit=6
    )
    yahoo_us = fetch_rss_items(
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC,%5EIXIC,%5EDJI&region=US&lang=en-US",
        source_label="Yahoo파이낸스",
        limit=5,
    )

    us_headlines = naver_us + google_us + investing_all[:3] + yahoo_us
    kr_headlines = naver_kr + google_kr + investing_all[3:]
    return us_headlines, kr_headlines


def summarize_with_ai(
    us_headlines: List[str], kr_headlines: List[str]
) -> Dict[str, Any]:
    """Gemini API 또는 OpenAI API를 사용해 심층 웹 리포트용 JSON을 생성합니다."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not gemini_key and not openai_key:
        override_file = BASE_DIR / "ai_summary_override.json"
        if override_file.exists():
            return json.loads(override_file.read_text(encoding="utf-8-sig"))
        raise RuntimeError("AI API 키 및 기본 요약 데이터가 없습니다.")

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8-sig")

    user_content = (
        "=== [간밤 미국/글로벌 증시 수집 뉴스] ===\n"
        + "\n".join(us_headlines)
        + "\n\n=== [국내 증시 시황 수집 뉴스] ===\n"
        + "\n".join(kr_headlines)
    )

    raw_reply = ""
    if gemini_key:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash:generateContent?key={gemini_key}"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": system_prompt + "\n\n" + user_content}],
                }
            ],
            "generationConfig": {
                "temperature": 0.25,
                "responseMimeType": "application/json",
            },
        }
        res = http_post_json(url, payload)
        raw_reply = (
            res.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
    elif openai_key:
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": "gpt-4o-mini",
            "response_format": {"type": "json_object"},
            "temperature": 0.25,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        res = http_post_json(
            url, payload, headers={"Authorization": f"Bearer {openai_key}"}
        )
        raw_reply = (
            res.get("choices", [{}])[0].get("message", {}).get("content", "")
        )

    cleaned_json = re.sub(
        r"^```(?:json)?|```$", "", raw_reply.strip(), flags=re.MULTILINE
    ).strip()
    return json.loads(cleaned_json)


def render_lesson_cards(lessons: List[Dict[str, str]]) -> str:
    """초보자용 경제 공부 카드 HTML을 렌더링합니다."""
    cards = []
    for item in lessons:
        term = html.escape(item.get("term", ""))
        why = html.escape(item.get("why_in_news", ""))
        easy = html.escape(item.get("easy_explanation", "")).replace("\n", "<br>")
        impact = html.escape(item.get("up_down_impact", "")).replace("\n", "<br>")
        cards.append(
            f"""
            <div class="lesson-card">
              <div class="lesson-badge">📚 오늘의 경제 공부</div>
              <h4 class="lesson-title">Q. {term}이(가) 뭔가요?</h4>
              <p class="lesson-why">💬 <strong>뉴스 맥락:</strong> {why}</p>
              <div class="lesson-box">
                <p><strong>💡 쉬운 개념 설명</strong><br>{easy}</p>
                <div class="impact-box">
                  <strong>📈 주가에는 어떤 영향을 주나요?</strong><br>{impact}
                </div>
              </div>
            </div>
            """
        )
    return "\n".join(cards)


def generate_html_report(
    report_data: Dict[str, Any], us_headlines: List[str], kr_headlines: List[str]
) -> pathlib.Path:
    """모바일 카카오톡 인앱 브라우저에 최적화된 상세 뉴스레터 웹페이지(docs/index.html)를 생성합니다."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    kst = datetime.timezone(datetime.timedelta(hours=9))
    now_kst = datetime.datetime.now(kst)
    weekdays_kr = ["월", "화", "수", "목", "금", "토", "일"]
    date_label = f"{now_kst.year}년 {now_kst.month:02d}월 {now_kst.day:02d}일 ({weekdays_kr[now_kst.weekday()]})"

    headline_title = html.escape(
        report_data.get("headline_title", "오늘의 미·한 증시 & 경제공부 브리핑")
    )
    three_lines = "\n".join(
        f"<li>{html.escape(line)}</li>"
        for line in report_data.get("three_line_summary", [])
    )
    us_paragraphs = "\n".join(
        f"<p>{html.escape(p)}</p>" for p in report_data.get("us_market_story", [])
    )
    kr_paragraphs = "\n".join(
        f"<p>{html.escape(p)}</p>" for p in report_data.get("kr_market_story", [])
    )
    us_lessons_html = render_lesson_cards(report_data.get("us_econ_lessons", []))
    kr_lessons_html = render_lesson_cards(report_data.get("kr_econ_lessons", []))

    checkpoints_html = "\n".join(
        f"<li>{html.escape(cp)}</li>"
        for cp in report_data.get("today_checkpoints", [])
    )
    raw_us_html = "\n".join(f"<li>{html.escape(h)}</li>" for h in us_headlines[:10])
    raw_kr_html = "\n".join(f"<li>{html.escape(h)}</li>" for h in kr_headlines[:10])

    html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <title>🌅 아침 주식 & 경제공부 브리핑 ({now_kst.strftime('%m/%d')})</title>
  <style>
    :root {{
      --bg: #f4f6f9;
      --card: #ffffff;
      --text: #191f28;
      --sub: #4e5968;
      --blue: #3182f6;
      --blue-bg: #e8f3ff;
      --amber-bg: #fff8eb;
      --amber-border: #ffd180;
      --border: #e5e8eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 16px 12px 48px;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Pretendard", "Noto Sans KR", "Malgun Gothic", sans-serif;
      line-height: 1.68;
      font-size: 16px;
    }}
    .container {{
      max-width: 640px;
      margin: 0 auto;
    }}
    .hero {{
      background: linear-gradient(135deg, #1b3a6b 0%, #2563eb 100%);
      color: #fff;
      padding: 24px 20px;
      border-radius: 18px;
      margin-bottom: 16px;
      box-shadow: 0 6px 20px rgba(37, 99, 235, 0.18);
    }}
    .hero-date {{
      font-size: 13px;
      opacity: 0.85;
      margin-bottom: 6px;
    }}
    .hero-title {{
      margin: 0;
      font-size: 21px;
      font-weight: 800;
      line-height: 1.4;
    }}
    .card {{
      background: var(--card);
      border-radius: 16px;
      padding: 20px;
      margin-bottom: 16px;
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
      border: 1px solid var(--border);
    }}
    .section-title {{
      margin: 0 0 14px;
      font-size: 18px;
      font-weight: 800;
      display: flex;
      align-items: center;
      gap: 6px;
      border-bottom: 2px solid #f2f4f6;
      padding-bottom: 10px;
    }}
    .summary-list {{
      margin: 0;
      padding-left: 20px;
    }}
    .summary-list li {{
      margin-bottom: 10px;
      font-weight: 500;
    }}
    .story p {{
      margin: 0 0 14px;
      color: #2b333e;
      word-break: keep-all;
    }}
    .lesson-card {{
      background: var(--amber-bg);
      border: 1px solid var(--amber-border);
      border-radius: 14px;
      padding: 16px;
      margin-top: 16px;
    }}
    .lesson-badge {{
      display: inline-block;
      background: #ff9800;
      color: #fff;
      font-size: 12px;
      font-weight: 700;
      padding: 3px 9px;
      border-radius: 99px;
      margin-bottom: 8px;
    }}
    .lesson-title {{
      margin: 0 0 8px;
      font-size: 16.5px;
      color: #191f28;
    }}
    .lesson-why {{
      margin: 0 0 10px;
      font-size: 14px;
      color: var(--sub);
    }}
    .lesson-box p {{
      margin: 0 0 12px;
      font-size: 15px;
    }}
    .impact-box {{
      background: #ffffff;
      border-radius: 10px;
      padding: 12px 14px;
      font-size: 14.5px;
      border-left: 4px solid var(--blue);
    }}
    .raw-list {{
      font-size: 13.5px;
      color: var(--sub);
      padding-left: 18px;
      margin: 8px 0 0;
    }}
    .raw-list li {{
      margin-bottom: 5px;
    }}
    details summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--blue);
      font-size: 15px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="hero">
      <div class="hero-date">🌅 모닝 주식 & 경제공부 리포트 · {date_label}</div>
      <h1 class="hero-title">{headline_title}</h1>
    </div>

    <div class="card">
      <h2 class="section-title">⚡ 바쁜 아침을 위한 3줄 핵심 요약</h2>
      <ul class="summary-list">
        {three_lines}
      </ul>
    </div>

    <div class="card">
      <h2 class="section-title">🇺🇸 1. 간밤 미국 증시 심층 해설</h2>
      <div class="story">
        {us_paragraphs}
      </div>
      {us_lessons_html}
    </div>

    <div class="card">
      <h2 class="section-title">🇰🇷 2. 국내 증시 시황 & 주도주 해설</h2>
      <div class="story">
        {kr_paragraphs}
      </div>
      {kr_lessons_html}
    </div>

    <div class="card">
      <h2 class="section-title">🎯 3. 오늘 장 투자자 체크포인트</h2>
      <ul class="summary-list">
        {checkpoints_html}
      </ul>
    </div>

    <div class="card">
      <details>
        <summary>📰 4대 매체(네이버·구글·인베스팅·야후) 수집 원문 헤드라인 보기</summary>
        <h4 style="margin:14px 0 4px;">🇺🇸 미국/글로벌 증시</h4>
        <ul class="raw-list">{raw_us_html}</ul>
        <h4 style="margin:14px 0 4px;">🇰🇷 국내 증시</h4>
        <ul class="raw-list">{raw_kr_html}</ul>
      </details>
    </div>
  </div>
</body>
</html>
"""
    out_path = DOCS_DIR / "index.html"
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


def refresh_kakao_access_token(
    rest_api_key: str, refresh_token: str, client_secret: str = ""
) -> str:
    """Refresh Token을 사용해 새로운 Access Token을 발급받습니다."""
    payload = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "refresh_token": refresh_token,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    data = http_post_form(KAKAO_TOKEN_URL, payload)
    return data["access_token"]


def send_kakao_memo(access_token: str, text: str, web_url: str) -> None:
    """카카오톡 '나에게 보내기' API로 텍스트 메시지를 발송합니다."""
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    template_object = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": web_url,
            "mobile_web_url": web_url,
        },
        "button_title": "상세 브리핑 & 경제공부 읽기",
    }
    res = http_post_form(
        KAKAO_MEMO_URL,
        form_data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        headers=headers,
    )
    if res.get("result_code") != 0:
        raise RuntimeError(f"카카오톡 메시지 전송 실패: {res}")


def prepare_report_and_message() -> Tuple[str, str, pathlib.Path]:
    """4개 뉴스 소스 수집 -> AI 리포트 생성 -> HTML 저장 및 카톡 알림 1통 구성을 수행합니다."""
    load_local_env()
    us_headlines, kr_headlines = collect_all_sources()

    print(
        f"[수집 완료] 미국/글로벌 뉴스 {len(us_headlines)}건, "
        f"국내 증시 뉴스 {len(kr_headlines)}건 (네이버·구글·인베스팅·야후)"
    )

    report_data = summarize_with_ai(us_headlines, kr_headlines)
    html_path = generate_html_report(report_data, us_headlines, kr_headlines)
    print(f"[웹 리포트 생성 완료] {html_path}")

    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%m/%d")
    preview = report_data.get("kakao_preview", "").strip()
    footer = f"\n\n👉 전체 읽기:\n{REPORT_WEB_URL}"
    header = f"🌅 모닝 증시 & 경제공부 ({today_str})\n\n"
    max_preview_len = 198 - len(header) - len(footer)
    if len(preview) > max_preview_len:
        preview = preview[: max_preview_len - 1] + "…"
    kakao_msg = f"{header}{preview}{footer}"

    return kakao_msg, REPORT_WEB_URL, html_path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_local_env()

    parser = argparse.ArgumentParser(
        description="4대 증시 뉴스를 수집하여 모바일 웹 리포트를 생성하고 카카오톡 알림을 발송합니다."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="카카오톡을 발송하지 않고 웹 리포트(docs/index.html) 생성 및 미리보기만 출력합니다.",
    )
    args = parser.parse_args()

    kakao_msg, report_url, html_path = prepare_report_and_message()

    print("=" * 60)
    print(f"카카오톡 발송 메시지 (1통, {len(kakao_msg)}자)")
    print("=" * 60)
    print(kakao_msg)
    print(f"🔗 연결 리포트 주소: {report_url}")
    print(f"📄 로컬 리포트 파일: {html_path}")
    print("=" * 60)

    if args.dry_run:
        print("[Dry-Run 완료] --dry-run 옵션이 켜져 있어 카카오톡 전송은 생략했습니다.")
        return

    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    access_token = refresh_kakao_access_token(
        rest_api_key=rest_api_key,
        refresh_token=refresh_token,
        client_secret=client_secret,
    )

    send_kakao_memo(access_token, kakao_msg, report_url)
    print("🎉 카카오톡 '나에게 보내기' 전송이 완료되었습니다!")


if __name__ == "__main__":
    main()
