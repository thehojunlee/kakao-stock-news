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
from typing import Dict, List, Tuple

BASE_DIR = pathlib.Path(__file__).resolve().parent
PROMPT_FILE = BASE_DIR / "ai_prompt.txt"
EXTERNAL_ENV_FILE = pathlib.Path(r"D:\FinanceData\kakao_stock_news.env")


def load_local_env() -> None:
    """볼트 외부(D:\\FinanceData\\kakao_stock_news.env)에 저장된 환경변수가 있으면 불러옵니다."""
    if not EXTERNAL_ENV_FILE.exists():
        return
    for line in EXTERNAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v and k not in os.environ:
            os.environ[k] = v

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} 오류 ({url}): {err_body}") from e


def clean_headline(raw_title: str, max_len: int = 80) -> str:
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
        us_keywords = ("뉴욕", "나스닥", "S&P", "다우", "미 증시", "미국증시", "월가", "연준", "Fed", "엔비디아", "테슬라")
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
) -> Tuple[str, str] | None:
    """Gemini API 또는 OpenAI API를 사용해 수집된 멀티소스 뉴스를 요약합니다."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if not gemini_key and not openai_key:
        return None

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else (
        "아래 미국 증시와 국내 증시 뉴스들을 각각 155자 이내의 불릿 3줄로 요약하여 "
        '{"us_summary": "...", "kr_summary": "..."} JSON 형식으로만 응답하세요.'
    )

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
                "temperature": 0.2,
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
            "temperature": 0.2,
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

    cleaned_json = re.sub(r"^```(?:json)?|```$", "", raw_reply.strip(), flags=re.MULTILINE).strip()
    parsed = json.loads(cleaned_json)
    return parsed.get("us_summary", "").strip(), parsed.get("kr_summary", "").strip()


def format_kakao_bubble(header: str, body: str) -> str:
    """카카오톡 텍스트 템플릿 200자 제한을 준수하도록 말풍선을 포맷팅합니다."""
    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%m/%d")
    full_text = f"{header} ({today_str})\n\n{body}"
    if len(full_text) > 198:
        full_text = full_text[:197] + "…"
    return full_text


def build_fallback_body(headlines: List[str], count: int = 3) -> str:
    """AI 키가 없을 때 사용할 기본 헤드라인 요약 본문을 만듭니다."""
    lines = []
    for idx, item in enumerate(headlines[:count], start=1):
        # [출처] 태그 뒤 제목을 40자로 다듬기
        short_item = item if len(item) <= 44 else item[:43] + "…"
        lines.append(f"{idx}. {short_item}")
    return "\n".join(lines) if lines else "수집된 최신 뉴스가 없습니다."


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
    if "refresh_token" in data:
        print(
            "[안내] 리프레시 토큰 만료 임박으로 새 refresh_token이 발급되었습니다. "
            "필요 시 GitHub Secrets의 KAKAO_REFRESH_TOKEN을 업데이트해주세요."
        )
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
        "button_title": "뉴스 더보기",
    }
    res = http_post_form(
        KAKAO_MEMO_URL,
        form_data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        headers=headers,
    )
    if res.get("result_code") != 0:
        raise RuntimeError(f"카카오톡 메시지 전송 실패: {res}")


def prepare_messages() -> List[Tuple[str, str]]:
    """4개 뉴스 소스에서 기사를 수집하고 AI 요약(또는 헤드라인 정리) 후 발송할 메시지 리스트를 반환합니다."""
    load_local_env()
    us_headlines, kr_headlines = collect_all_sources()

    print(
        f"[수집 완료] 미국/글로벌 뉴스 {len(us_headlines)}건, "
        f"국내 증시 뉴스 {len(kr_headlines)}건 (네이버·구글·인베스팅·야후)"
    )

    ai_result = None
    try:
        ai_result = summarize_with_ai(us_headlines, kr_headlines)
    except Exception as e:
        print(f"[경고] AI 요약 중 오류가 발생하여 기본 헤드라인 모드로 전환합니다: {e}", file=sys.stderr)

    if ai_result and ai_result[0] and ai_result[1]:
        print("[AI 요약 완료] ai_prompt.txt 지침에 따라 종합 요약을 생성했습니다.")
        us_body, kr_body = ai_result
        us_msg = format_kakao_bubble("🇺🇸 미국 증시 AI 종합", us_body)
        kr_msg = format_kakao_bubble("🇰🇷 국내 증시 AI 종합", kr_body)
    else:
        print(
            "[안내] GEMINI_API_KEY(또는 OPENAI_API_KEY)가 설정되지 않아 "
            "멀티소스 대표 헤드라인 모드로 생성합니다."
        )
        us_body = build_fallback_body(us_headlines, count=3)
        kr_body = build_fallback_body(kr_headlines, count=3)
        us_msg = format_kakao_bubble("🇺🇸 간밤 미국 증시 종합", us_body)
        kr_msg = format_kakao_bubble("🇰🇷 오늘 국내 증시 종합", kr_body)

    return [
        (us_msg, "https://finance.naver.com/world/"),
        (kr_msg, "https://finance.naver.com/news/mainnews.nhn"),
    ]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    load_local_env()

    parser = argparse.ArgumentParser(
        description="4대 증시 뉴스 소스(네이버·구글·인베스팅·야후)를 수집 및 AI 요약하여 카카오톡으로 발송합니다."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="카카오톡을 실제로 발송하지 않고 수집된 뉴스와 메시지 포맷만 콘솔에 출력합니다.",
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="4개 사이트에서 수집된 원본 헤드라인 전체를 함께 출력합니다.",
    )
    args = parser.parse_args()

    if args.show_raw:
        us_raw, kr_raw = collect_all_sources()
        print("\n[원본 수집 데이터: 미국/글로벌 증시]")
        for item in us_raw:
            print(" -", item)
        print("\n[원본 수집 데이터: 국내 증시]")
        for item in kr_raw:
            print(" -", item)
        print()

    messages_to_send = prepare_messages()

    print("=" * 55)
    print("수집된 카카오톡 발송 예정 메시지 미리보기")
    print("=" * 55)
    for msg_text, more_url in messages_to_send:
        print(msg_text)
        print(f"🔗 링크: {more_url} (글자수: {len(msg_text)}자)")
        print("-" * 55)

    if args.dry_run:
        print("[Dry-Run 완료] --dry-run 옵션이 켜져 있어 카카오톡 전송은 생략했습니다.")
        return

    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    if not rest_api_key or not refresh_token:
        print(
            "[오류] 환경변수 KAKAO_REST_API_KEY 또는 KAKAO_REFRESH_TOKEN이 설정되지 않았습니다.\n"
            "먼저 1_get_token.bat을 실행하거나 --dry-run 옵션으로 테스트해보세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    access_token = refresh_kakao_access_token(
        rest_api_key=rest_api_key,
        refresh_token=refresh_token,
        client_secret=client_secret,
    )

    for msg_text, more_url in messages_to_send:
        send_kakao_memo(access_token, msg_text, more_url)

    print("카카오톡 '나에게 보내기' 전송이 완료되었습니다!")


if __name__ == "__main__":
    main()
