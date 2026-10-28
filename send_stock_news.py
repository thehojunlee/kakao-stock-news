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
KAKAO_FRIENDS_LIST_URL = "https://kapi.kakao.com/v1/api/talk/friends"
KAKAO_FRIENDS_SEND_URL = "https://kapi.kakao.com/v1/api/talk/friends/message/default/send"

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


def format_rich_text(text: str) -> str:
    """HTML 이스케이프 후 **강조** 문법을 <strong> 태그로, 줄바꿈을 <br>로 변환합니다."""
    escaped = html.escape(text)
    bolded = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return bolded.replace("\n", "<br>")


def clean_headline(raw_title: str, max_len: int = 92) -> str:
    """언론사 접미사 제거 및 깔끔한 한 줄 제목으로 정리합니다."""
    title = html.unescape(raw_title).strip()
    if " - " in title:
        title = title.rsplit(" - ", 1)[0].strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) > max_len:
        title = title[: max_len - 1].rstrip() + "…"
    return title


def fetch_rss_items(
    rss_url: str, source_label: str, limit: int = 5
) -> Tuple[List[Dict[str, str]], List[str]]:
    """지정된 RSS URL에서 최신 뉴스 아이템({source, title, url}) 목록과 썸네일 이미지 URL을 가져옵니다."""
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_bytes = resp.read()
        raw_text = xml_bytes.decode("utf-8", errors="replace")
        images = re.findall(r'url="(https://content-media\.investing\.com/[^"]+)"', raw_text)

        root = ET.fromstring(xml_bytes)
        results: List[Dict[str, str]] = []
        seen = set()
        for item in root.findall("./channel/item"):
            raw_title = item.findtext("title") or ""
            link = (item.findtext("link") or "").strip()
            cleaned = clean_headline(raw_title)
            if not cleaned:
                continue
            prefix = re.sub(r"[^\w가-힣]", "", cleaned.lower())[:14]
            if prefix in seen:
                continue
            seen.add(prefix)
            results.append(
                {
                    "source": source_label,
                    "title": cleaned,
                    "url": link or "https://finance.naver.com/",
                }
            )
            if len(results) >= limit:
                break
        return results, images
    except Exception as e:
        print(f"[경고] {source_label} 수집 중 오류 발생 (건너뜀): {e}", file=sys.stderr)
        return [], []


def fetch_google_news_rss(
    query: str, source_label: str, limit: int = 5
) -> List[Dict[str, str]]:
    """구글 뉴스 한국어 RSS에서 검색어 기준 최신 뉴스와 링크를 가져옵니다."""
    encoded_query = urllib.parse.quote(query)
    rss_url = (
        f"https://news.google.com/rss/search?q={encoded_query}"
        f"&hl=ko&gl=KR&ceid=KR:ko"
    )
    items, _ = fetch_rss_items(rss_url, source_label=source_label, limit=limit)
    return items


def fetch_naver_securities_news(
    limit: int = 6,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """네이버 증권 속보/주요뉴스 섹션에서 기사와 원문 링크를 함께 추출합니다."""
    url = "https://news.naver.com/breakingnews/section/101/258"
    us_list: List[Dict[str, str]] = []
    kr_list: List[Dict[str, str]] = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")

        pairs = re.findall(
            r'<a href="(https://n\.news\.naver\.com/[^"]+)" class="sa_text_title[^"]*"[^>]*>\s*<strong class="sa_text_strong">([^<]+)</strong>',
            raw_html,
        )
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
        for link, raw_title in pairs:
            cleaned = clean_headline(raw_title)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            entry = {"source": "네이버증권", "title": cleaned, "url": html.unescape(link)}
            if any(k in cleaned for k in us_keywords):
                if len(us_list) < limit:
                    us_list.append(entry)
            else:
                if len(kr_list) < limit:
                    kr_list.append(entry)
    except Exception as e:
        print(f"[경고] 네이버 증권 뉴스 수집 중 오류 발생 (건너뜀): {e}", file=sys.stderr)

    return us_list, kr_list


def fetch_upbit_btc_svg_chart() -> str:
    """업비트 공개 API에서 최근 30일 비트코인(KRW-BTC) 일봉을 가져와 깔끔한 SVG 차트로 렌더링합니다."""
    try:
        url = "https://api.upbit.com/v1/candles/days?market=KRW-BTC&count=30"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            candles = json.loads(resp.read().decode("utf-8"))
        if not candles:
            return ""
        candles = list(reversed(candles))
        prices = [float(c["trade_price"]) for c in candles]
        latest_krw = int(prices[-1])
        chg_pct = float(candles[-1].get("change_rate", 0.0)) * 100
        sign = "+" if chg_pct >= 0 else ""

        min_p, max_p = min(prices), max(prices)
        span = max(max_p - min_p, 1.0)
        w, h = 280, 125
        pad_x, pad_y = 10, 16

        pts = []
        for idx, p in enumerate(prices):
            x = pad_x + (idx / max(len(prices) - 1, 1)) * (w - 2 * pad_x)
            y = pad_y + (1.0 - (p - min_p) / span) * (h - 2 * pad_y)
            pts.append(f"{x:.1f},{y:.1f}")

        polyline_pts = " ".join(pts)
        area_pts = f"{pad_x},{h - pad_y} " + polyline_pts + f" {w - pad_x},{h - pad_y}"

        return f"""
        <svg viewBox="0 0 {w} {h + 24}" width="100%" height="auto" style="background:#fff;border-radius:8px;display:block;">
          <defs>
            <linearGradient id="btcGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#f59e0b" stop-opacity="0.38"/>
              <stop offset="100%" stop-color="#f59e0b" stop-opacity="0.02"/>
            </linearGradient>
          </defs>
          <polygon points="{area_pts}" fill="url(#btcGrad)" />
          <polyline fill="none" stroke="#d97706" stroke-width="2.5" points="{polyline_pts}" />
          <text x="10" y="15" font-size="11" fill="#64748b" font-family="sans-serif">최고 {int(max_p)//10000:,}만원</text>
          <text x="10" y="{h + 15}" font-size="11" fill="#64748b" font-family="sans-serif">최저 {int(min_p)//10000:,}만원</text>
          <text x="{w - 10}" y="{h + 15}" text-anchor="end" font-size="11.5" font-weight="bold" fill="#b45309" font-family="sans-serif">현재 {latest_krw//10000:,}만원 ({sign}{chg_pct:.2f}%)</text>
        </svg>
        """
    except Exception:
        return ""


def collect_all_sources() -> Tuple[
    List[Dict[str, str]],
    List[Dict[str, str]],
    List[Dict[str, str]],
    List[str],
]:
    """미국 증시, 국내 증시, 비트코인·금 뉴스 및 이미지를 종합 수집합니다."""
    naver_us, naver_kr = fetch_naver_securities_news(limit=5)

    google_us = fetch_google_news_rss(
        "뉴욕증시 OR 미국증시 OR 나스닥 마감 when:1d", source_label="구글뉴스", limit=5
    )
    google_kr = fetch_google_news_rss(
        "코스피 시황 OR 국내증시 OR 장마감 시황 OR 출발 시황 when:1d",
        source_label="구글뉴스",
        limit=5,
    )
    google_btc = fetch_google_news_rss(
        "비트코인 시황 OR 비트코인 가격 OR 암호화폐 when:1d",
        source_label="구글뉴스(코인)",
        limit=4,
    )
    google_gold = fetch_google_news_rss(
        "국제금시세 OR 금값 OR 금시세 안전자산 when:1d",
        source_label="구글뉴스(금)",
        limit=4,
    )

    investing_all, investing_imgs = fetch_rss_items(
        "https://kr.investing.com/rss/news_25.rss", source_label="인베스팅닷컴", limit=6
    )
    yahoo_us, _ = fetch_rss_items(
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC,%5EIXIC,%5EDJI&region=US&lang=en-US",
        source_label="Yahoo파이낸스",
        limit=4,
    )
    yahoo_btc_gold, _ = fetch_rss_items(
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=BTC-USD,GC%3DF&region=US&lang=en-US",
        source_label="Yahoo(BTC·Gold)",
        limit=3,
    )

    us_items = naver_us + google_us + investing_all[:3] + yahoo_us
    kr_items = naver_kr + google_kr + investing_all[3:]
    crypto_gold_items = google_btc + google_gold + yahoo_btc_gold

    return us_items, kr_items, crypto_gold_items, investing_imgs


def format_items_for_prompt(items: List[Dict[str, str]]) -> str:
    return "\n".join(f"[{it['source']}] {it['title']}" for it in items)


def summarize_with_ai(
    us_items: List[Dict[str, str]],
    kr_items: List[Dict[str, str]],
    crypto_gold_items: List[Dict[str, str]],
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
        + format_items_for_prompt(us_items)
        + "\n\n=== [국내 증시 시황 수집 뉴스] ===\n"
        + format_items_for_prompt(kr_items)
        + "\n\n=== [비트코인(가상자산) 및 금(안전자산) 수집 뉴스] ===\n"
        + format_items_for_prompt(crypto_gold_items)
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


def render_story_blocks(blocks: List[Dict[str, str]]) -> str:
    """소제목 + 형광펜 핵심 요약 + 굵은 글씨 본문 블록을 렌더링합니다."""
    out = []
    for b in blocks:
        subtitle = html.escape(b.get("subtitle", ""))
        highlight = format_rich_text(b.get("highlight", ""))
        body = format_rich_text(b.get("body", ""))
        out.append(
            f"""
            <div class="story-block">
              <h3 class="story-subtitle">{subtitle}</h3>
              <div class="story-highlight">💡 {highlight}</div>
              <p class="story-body">{body}</p>
            </div>
            """
        )
    return "\n".join(out)


def render_lesson_cards(lessons: List[Dict[str, str]]) -> str:
    """초보자용 경제 공부 카드(인과관계 화살표 공식 + 호재/악재 비교 박스)를 렌더링합니다."""
    cards = []
    for item in lessons:
        term = html.escape(item.get("term", ""))
        why = format_rich_text(item.get("why_in_news", ""))
        easy = format_rich_text(item.get("easy_explanation", ""))
        flow = html.escape(item.get("flow_formula", ""))
        pos = format_rich_text(item.get("positive_case", ""))
        neg = format_rich_text(item.get("negative_case", ""))

        flow_html = (
            f'<div class="flow-diagram"><span class="flow-tag">🧭 한 줄 공식</span> {flow}</div>'
            if flow
            else ""
        )

        cards.append(
            f"""
            <div class="lesson-card">
              <div class="lesson-badge">📚 주린이 탈출 · 오늘의 경제 공부</div>
              <h4 class="lesson-title">Q. {term}이(가) 뭔가요?</h4>
              <p class="lesson-why">📰 {why}</p>
              <div class="lesson-easy">{easy}</div>
              {flow_html}
              <div class="impact-grid">
                <div class="impact-pos">
                  <div class="impact-header">📈 가격에 긍정적일 때 (호재 원리)</div>
                  <div>{pos}</div>
                </div>
                <div class="impact-neg">
                  <div class="impact-header">📉 가격에 부담될 때 (주의 원리)</div>
                  <div>{neg}</div>
                </div>
              </div>
            </div>
            """
        )
    return "\n".join(cards)


def render_headline_links(items: List[Dict[str, str]], limit: int = 12) -> str:
    """수집된 각 기사별 클릭 가능한 원문 링크 목록을 렌더링합니다."""
    rows = []
    for it in items[:limit]:
        src = html.escape(it.get("source", ""))
        title = html.escape(it.get("title", ""))
        url = html.escape(it.get("url", "https://finance.naver.com/"))
        rows.append(
            f"""
            <li class="raw-item">
              <a href="{url}" target="_blank" rel="noopener noreferrer" class="raw-link">
                <span class="raw-source">[{src}]</span> {title}
                <span class="raw-arrow">원문 보기 ↗</span>
              </a>
            </li>
            """
        )
    return "\n".join(rows)


def generate_html_report(
    report_data: Dict[str, Any],
    us_items: List[Dict[str, str]],
    kr_items: List[Dict[str, str]],
    crypto_gold_items: List[Dict[str, str]],
    news_images: List[str],
) -> pathlib.Path:
    """시각적 차트 이미지, 비트코인/금 섹션, 기사별 원문 링크가 포함된 모바일 리포트(docs/index.html)를 생성합니다."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    kst = datetime.timezone(datetime.timedelta(hours=9))
    now_kst = datetime.datetime.now(kst)
    weekdays_kr = ["월", "화", "수", "목", "금", "토", "일"]
    date_label = f"{now_kst.year}년 {now_kst.month:02d}월 {now_kst.day:02d}일 ({weekdays_kr[now_kst.weekday()]})"
    cache_bust = now_kst.strftime("%Y%m%d%H")

    headline_title = html.escape(
        report_data.get("headline_title", "오늘의 미·한 증시 & 비트코인·금 경제공부 브리핑")
    )

    # 1. 상단 6대 시장 지표 전광판
    metrics_html_list = []
    for m in report_data.get("market_metrics", []):
        trend = m.get("trend", "neutral")
        trend_class = "metric-up" if trend == "up" else ("metric-down" if trend == "down" else "metric-neutral")
        metrics_html_list.append(
            f"""
            <div class="metric-card {trend_class}">
              <div class="metric-label">{html.escape(m.get('label', ''))}</div>
              <div class="metric-value">{html.escape(m.get('value', ''))}</div>
              <div class="metric-sub">{html.escape(m.get('sub', ''))}</div>
            </div>
            """
        )
    metrics_grid_html = "\n".join(metrics_html_list)

    # 2. 3줄 요약
    three_lines = "\n".join(
        f"<li>{format_rich_text(line)}</li>"
        for line in report_data.get("three_line_summary", [])
    )

    # 3. 미국 / 국내 / 비트코인·금 스토리 블록 & 경제 공부 카드
    us_blocks_html = render_story_blocks(report_data.get("us_market_blocks", []))
    kr_blocks_html = render_story_blocks(report_data.get("kr_market_blocks", []))
    cg_blocks_html = render_story_blocks(report_data.get("crypto_gold_blocks", []))

    us_lessons_html = render_lesson_cards(report_data.get("us_econ_lessons", []))
    kr_lessons_html = render_lesson_cards(report_data.get("kr_econ_lessons", []))
    cg_lessons_html = render_lesson_cards(report_data.get("crypto_gold_lessons", []))

    btc_svg_html = fetch_upbit_btc_svg_chart()

    checkpoints_html = "\n".join(
        f"<li>{format_rich_text(cp)}</li>"
        for cp in report_data.get("today_checkpoints", [])
    )

    raw_us_html = render_headline_links(us_items, limit=12)
    raw_kr_html = render_headline_links(kr_items, limit=12)
    raw_cg_html = render_headline_links(crypto_gold_items, limit=12)

    featured_photo = (
        news_images[0]
        if news_images
        else "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1000&q=80"
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <title>🌅 모닝 주식·코인·금 & 경제공부 리포트 ({now_kst.month:02d}/{now_kst.day:02d})</title>
  <style>
    :root {{
      --bg: #f2f4f8;
      --card: #ffffff;
      --text: #191f28;
      --sub: #4e5968;
      --blue: #2563eb;
      --red: #e11d48;
      --red-bg: #fff1f2;
      --amber-bg: #fffbeb;
      --amber-border: #fde68a;
      --border: #e5e8eb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 14px 12px 56px;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Pretendard", "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", sans-serif;
      line-height: 1.72;
      font-size: 16px;
      -webkit-font-smoothing: antialiased;
    }}
    .container {{
      max-width: 640px;
      margin: 0 auto;
    }}
    .hero {{
      position: relative;
      background: linear-gradient(135deg, rgba(15, 23, 42, 0.88) 0%, rgba(30, 58, 138, 0.84) 100%),
                  url('{featured_photo}') center/cover no-repeat;
      color: #fff;
      padding: 28px 22px;
      border-radius: 20px;
      margin-bottom: 16px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
    }}
    .hero-badge {{
      display: inline-block;
      background: rgba(255, 255, 255, 0.18);
      backdrop-filter: blur(4px);
      padding: 4px 11px;
      border-radius: 99px;
      font-size: 12.5px;
      font-weight: 600;
      margin-bottom: 10px;
    }}
    .hero-title {{
      margin: 0;
      font-size: 21.5px;
      font-weight: 800;
      line-height: 1.42;
      word-break: keep-all;
    }}
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-bottom: 16px;
    }}
    .metric-card {{
      background: var(--card);
      border-radius: 15px;
      padding: 13px 14px;
      border: 1px solid var(--border);
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
    }}
    .metric-label {{
      font-size: 13px;
      color: var(--sub);
      font-weight: 600;
      margin-bottom: 3px;
    }}
    .metric-value {{
      font-size: 18px;
      font-weight: 800;
      letter-spacing: -0.3px;
    }}
    .metric-up .metric-value {{ color: var(--red); }}
    .metric-down .metric-value {{ color: var(--blue); }}
    .metric-neutral .metric-value {{ color: #1e293b; }}
    .metric-sub {{
      font-size: 12px;
      color: var(--sub);
      margin-top: 2px;
    }}
    .card {{
      background: var(--card);
      border-radius: 18px;
      padding: 22px 18px;
      margin-bottom: 18px;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
      border: 1px solid var(--border);
    }}
    .section-title {{
      margin: 0 0 16px;
      font-size: 19px;
      font-weight: 800;
      display: flex;
      align-items: center;
      gap: 7px;
      border-bottom: 2px solid #f1f5f9;
      padding-bottom: 12px;
      color: #0f172a;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-bottom: 18px;
    }}
    @media (max-width: 480px) {{
      .chart-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    .chart-box {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      padding: 10px;
      text-align: center;
    }}
    .chart-caption {{
      font-size: 13px;
      font-weight: 700;
      color: #334155;
      margin-bottom: 6px;
    }}
    .chart-box img {{
      width: 100%;
      height: auto;
      border-radius: 8px;
      background: #fff;
      display: block;
    }}
    .summary-list {{
      margin: 0;
      padding-left: 20px;
    }}
    .summary-list li {{
      margin-bottom: 12px;
      font-size: 15.5px;
      word-break: keep-all;
    }}
    .summary-list li:last-child {{ margin-bottom: 0; }}
    .story-block {{
      padding: 16px;
      background: #f8fafc;
      border-radius: 14px;
      margin-bottom: 14px;
      border: 1px solid #eef2f6;
    }}
    .story-subtitle {{
      margin: 0 0 8px;
      font-size: 16.5px;
      font-weight: 800;
      color: #1e293b;
      word-break: keep-all;
    }}
    .story-highlight {{
      background: #fef08a;
      color: #1e293b;
      padding: 7px 11px;
      border-radius: 8px;
      font-size: 14.5px;
      font-weight: 700;
      margin-bottom: 10px;
      line-height: 1.5;
      word-break: keep-all;
    }}
    .story-body {{
      margin: 0;
      font-size: 15.5px;
      color: #334155;
      word-break: keep-all;
    }}
    .story-body strong {{
      color: #0f172a;
      background: linear-gradient(transparent 65%, #dbeafe 65%);
    }}
    .lesson-card {{
      background: var(--amber-bg);
      border: 1.5px solid var(--amber-border);
      border-radius: 16px;
      padding: 18px 16px;
      margin-top: 18px;
    }}
    .lesson-badge {{
      display: inline-block;
      background: #d97706;
      color: #fff;
      font-size: 12px;
      font-weight: 800;
      padding: 4px 10px;
      border-radius: 99px;
      margin-bottom: 8px;
    }}
    .lesson-title {{
      margin: 0 0 6px;
      font-size: 17.5px;
      font-weight: 800;
      color: #111827;
    }}
    .lesson-why {{
      margin: 0 0 10px;
      font-size: 13.5px;
      color: #6b7280;
    }}
    .lesson-easy {{
      background: #ffffff;
      padding: 12px 14px;
      border-radius: 10px;
      font-size: 15px;
      margin-bottom: 10px;
      border: 1px solid #fde68a;
      word-break: keep-all;
    }}
    .flow-diagram {{
      background: #1e293b;
      color: #f8fafc;
      padding: 11px 13px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 700;
      margin-bottom: 12px;
      line-height: 1.5;
      word-break: keep-all;
    }}
    .flow-tag {{
      display: inline-block;
      background: #3b82f6;
      color: #fff;
      font-size: 11.5px;
      padding: 2px 7px;
      border-radius: 6px;
      margin-right: 6px;
    }}
    .impact-grid {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .impact-pos {{
      background: var(--red-bg);
      border-left: 4px solid var(--red);
      padding: 12px 14px;
      border-radius: 10px;
      font-size: 14.5px;
      word-break: keep-all;
    }}
    .impact-neg {{
      background: #eff6ff;
      border-left: 4px solid var(--blue);
      padding: 12px 14px;
      border-radius: 10px;
      font-size: 14.5px;
      word-break: keep-all;
    }}
    .impact-header {{
      font-weight: 800;
      margin-bottom: 4px;
      font-size: 15px;
    }}
    .impact-pos .impact-header {{ color: #be123c; }}
    .impact-neg .impact-header {{ color: #1d4ed8; }}
    /* 수집 원문 링크 리스트 */
    .raw-list {{
      list-style: none;
      padding: 0;
      margin: 10px 0 0;
    }}
    .raw-item {{
      margin-bottom: 8px;
    }}
    .raw-link {{
      display: block;
      padding: 10px 12px;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      color: #1e293b;
      text-decoration: none;
      font-size: 14px;
      line-height: 1.45;
      transition: background 0.15s;
    }}
    .raw-link:hover, .raw-link:active {{
      background: #eff6ff;
      border-color: #bfdbfe;
    }}
    .raw-source {{
      font-weight: 800;
      color: var(--blue);
      margin-right: 4px;
    }}
    .raw-arrow {{
      display: inline-block;
      margin-left: 6px;
      font-size: 12px;
      font-weight: 700;
      color: #64748b;
      background: #e2e8f0;
      padding: 1px 6px;
      border-radius: 5px;
    }}
    .raw-cat-title {{
      margin: 18px 0 8px;
      font-size: 15.5px;
      font-weight: 800;
      color: #0f172a;
    }}
  </style>
</head>
<body>
  <div class="container">
    <!-- 상단 배너 -->
    <div class="hero">
      <div class="hero-badge">🌅 모닝 주식·코인·금 & 경제공부 리포트 · {date_label}</div>
      <h1 class="hero-title">{headline_title}</h1>
    </div>

    <!-- 한눈에 보는 6대 핵심 전광판 -->
    <div class="metrics-grid">
      {metrics_grid_html}
    </div>

    <!-- 바쁜 아침 3줄 요약 -->
    <div class="card">
      <h2 class="section-title">⚡ 바쁜 아침을 위한 3줄 핵심 요약</h2>
      <ul class="summary-list">
        {three_lines}
      </ul>
    </div>

    <!-- 1. 미국 증시 섹션 -->
    <div class="card">
      <h2 class="section-title">🇺🇸 1. 간밤 미국 증시 심층 해설</h2>
      <div class="chart-grid">
        <div class="chart-box">
          <div class="chart-caption">📊 나스닥 종합 일봉 차트</div>
          <img src="https://ssl.pstatic.net/imgfinance/chart/mobile/world/day/NAS@IXIC_end.png?t={cache_bust}" alt="나스닥 차트" loading="lazy">
        </div>
        <div class="chart-box">
          <div class="chart-caption">📊 S&P 500 일봉 차트</div>
          <img src="https://ssl.pstatic.net/imgfinance/chart/mobile/world/day/SPI@SPX_end.png?t={cache_bust}" alt="S&P500 차트" loading="lazy">
        </div>
      </div>
      {us_blocks_html}
      {us_lessons_html}
    </div>

    <!-- 2. 국내 증시 섹션 -->
    <div class="card">
      <h2 class="section-title">🇰🇷 2. 국내 증시 시황 & 주도주 해설</h2>
      <div class="chart-grid">
        <div class="chart-box">
          <div class="chart-caption">📈 코스피(KOSPI) 일봉 캔들 차트</div>
          <img src="https://ssl.pstatic.net/imgfinance/chart/mobile/candle/day/KOSPI_end.png?t={cache_bust}" alt="코스피 차트" loading="lazy">
        </div>
        <div class="chart-box">
          <div class="chart-caption">💵 원/달러 환율 추이 (3개월)</div>
          <img src="https://ssl.pstatic.net/imgfinance/chart/mobile/marketindex/month3/FX_USDKRW_end.png?t={cache_bust}" alt="원달러 환율 차트" loading="lazy">
        </div>
      </div>
      {kr_blocks_html}
      {kr_lessons_html}
    </div>

    <!-- 3. 비트코인 & 금 섹션 -->
    <div class="card">
      <h2 class="section-title">🪙 3. 비트코인(가상자산) & 🥇 금(안전자산) 해설</h2>
      <div class="chart-grid">
        <div class="chart-box">
          <div class="chart-caption">₿ 비트코인 최근 30일 추이 (업비트 기준)</div>
          {btc_svg_html}
        </div>
        <div class="chart-box">
          <div class="chart-caption">🥇 국제 금 시세 추이 (3개월)</div>
          <img src="https://ssl.pstatic.net/imgfinance/chart/mobile/marketindex/month3/CMDT_GC_end.png?t={cache_bust}" alt="국제 금 시세 차트" loading="lazy">
        </div>
      </div>
      {cg_blocks_html}
      {cg_lessons_html}
    </div>

    <!-- 4. 오늘 장 체크포인트 -->
    <div class="card">
      <h2 class="section-title">🎯 4. 오늘의 투자자 체크포인트</h2>
      <ul class="summary-list">
        {checkpoints_html}
      </ul>
    </div>

    <!-- 5. 수집 원문 헤드라인 & 기사별 바로가기 링크 -->
    <div class="card">
      <h2 class="section-title">📰 5. 수집 원문 헤드라인 & 기사 바로가기</h2>
      <p style="margin:0 0 10px;font-size:13.5px;color:#64748b;">각 기사 제목을 터치하면 해당 언론사의 원문 기사로 바로 이동합니다.</p>
      <div class="raw-cat-title">🇺🇸 미국/글로벌 증시 원문</div>
      <ul class="raw-list">{raw_us_html}</ul>
      <div class="raw-cat-title">🇰🇷 국내 증시 원문</div>
      <ul class="raw-list">{raw_kr_html}</ul>
      <div class="raw-cat-title">🪙 비트코인 & 🥇 금 시황 원문</div>
      <ul class="raw-list">{raw_cg_html}</ul>
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


def send_kakao_to_friends(access_token: str, text: str, web_url: str) -> int:
    """동의한 카카오 친구 목록을 조회하여 1:1 카톡방으로 동일한 브리핑을 발송합니다."""
    req = urllib.request.Request(
        KAKAO_FRIENDS_LIST_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        # 아직 friends 동의항목을 켜지 않았거나 친구가 없는 경우 조용히 넘어감
        return 0

    elements = data.get("elements", [])
    uuids = [f["uuid"] for f in elements if "uuid" in f][:5]
    if not uuids:
        return 0

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
        KAKAO_FRIENDS_SEND_URL,
        form_data={
            "receiver_uuids": json.dumps(uuids),
            "template_object": json.dumps(template_object, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    succeeded = res.get("successful_receiver_uuids", [])
    return len(succeeded)


def prepare_report_and_message() -> Tuple[str, str, pathlib.Path]:
    """4개 뉴스 소스(미·한 증시 + 비트코인·금) 수집 -> AI 리포트 생성 -> HTML 저장 및 카톡 알림 구성을 수행합니다."""
    load_local_env()
    us_items, kr_items, crypto_gold_items, news_images = collect_all_sources()

    print(
        f"[수집 완료] 미국 {len(us_items)}건, 국내 {len(kr_items)}건, "
        f"비트코인·금 {len(crypto_gold_items)}건, 이미지 {len(news_images)}건"
    )

    report_data = summarize_with_ai(us_items, kr_items, crypto_gold_items)
    html_path = generate_html_report(
        report_data, us_items, kr_items, crypto_gold_items, news_images
    )
    print(f"[웹 리포트 생성 완료] {html_path}")

    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%m/%d")
    preview = report_data.get("kakao_preview", "").strip()
    header = f"🌅 모닝 증시·코인·금 ({today_str})\n\n"
    max_preview_len = 198 - len(header)
    if len(preview) > max_preview_len:
        preview = preview[: max_preview_len - 1] + "…"
    kakao_msg = f"{header}{preview}"

    return kakao_msg, REPORT_WEB_URL, html_path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_local_env()

    parser = argparse.ArgumentParser(
        description="미·한 증시 및 비트코인·금 뉴스를 수집하여 모바일 웹 리포트를 생성하고 카카오톡 알림을 발송합니다."
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
    friend_cnt = send_kakao_to_friends(access_token, kakao_msg, report_url)
    if friend_cnt > 0:
        print(f"🎉 나에게 보내기 + 친구 {friend_cnt}명에게 1:1 카톡 전송이 완료되었습니다!")
    else:
        print("🎉 카카오톡 '나에게 보내기' 전송이 완료되었습니다!")


if __name__ == "__main__":
    main()
