import http.server
import os
import pathlib
import subprocess
import sys
import urllib.parse
import webbrowser

import send_stock_news

REDIRECT_URI = "http://localhost:5000/oauth"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
EXTERNAL_ENV_FILE = pathlib.Path(r"D:\FinanceData\kakao_stock_news.env")


def save_env_key(key: str, value: str) -> None:
    """볼트 외부 D:\\FinanceData\\kakao_stock_news.env 파일에 키를 저장/업데이트합니다."""
    EXTERNAL_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    env_map: dict[str, str] = {}
    if EXTERNAL_ENV_FILE.exists():
        for line in EXTERNAL_ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env_map[k.strip()] = v.strip()
    env_map[key] = value
    lines = [f"{k}={v}" for k, v in env_map.items() if v]
    EXTERNAL_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    auth_code: str | None = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs and qs["code"]:
            OAuthCallbackHandler.auth_code = qs["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html_body = (
                "<html><body style='font-family:sans-serif;text-align:center;padding-top:60px;'>"
                "<h2>✅ 카카오 인증 완료!</h2>"
                "<p>지금 카카오톡으로 뉴스를 발송 중입니다. 이 창은 닫으셔도 됩니다.</p>"
                "</body></html>"
            )
            self.wfile.write(html_body.encode("utf-8"))
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<html><body><h2>인증 코드가 없습니다. 다시 시도해주세요.</h2></body></html>".encode(
                    "utf-8"
                )
            )

    def log_message(self, format: str, *args) -> None:
        pass


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    send_stock_news.load_local_env()
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()

    if not rest_api_key:
        rest_api_key = input("👉 카카오 앱의 [REST API 키]를 붙여넣고 Enter를 누르세요: ").strip()
    if not rest_api_key:
        print("[오류] REST API 키가 입력되지 않았습니다.")
        sys.exit(1)

    save_env_key("KAKAO_REST_API_KEY", rest_api_key)

    auth_url = (
        f"https://kauth.kakao.com/oauth/authorize?"
        f"client_id={rest_api_key}&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code&scope=talk_message"
    )

    print("🌐 브라우저에서 노란색 [동의하고 계속하기](또는 [계속하기]) 버튼을 눌러주세요...")
    webbrowser.open(auth_url)

    server = http.server.HTTPServer(("localhost", 5000), OAuthCallbackHandler)
    while OAuthCallbackHandler.auth_code is None:
        server.handle_request()
    auth_code = OAuthCallbackHandler.auth_code
    server.server_close()

    if not auth_code:
        print("[오류] 시간 내에 브라우저 인증이 완료되지 않았습니다.")
        sys.exit(1)

    payload = {
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "code": auth_code,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    token_data = send_stock_news.http_post_form(TOKEN_URL, payload)
    refresh_token = token_data.get("refresh_token", "")
    access_token = token_data.get("access_token", "")

    save_env_key("KAKAO_REFRESH_TOKEN", refresh_token)
    print("✅ 토큰이 D:\\FinanceData\\kakao_stock_news.env에 자동 저장되었습니다!")

    # GitHub Secrets에도 자동 등록
    try:
        subprocess.run(
            ["gh", "secret", "set", "KAKAO_REST_API_KEY"],
            input=rest_api_key.encode("utf-8"),
            cwd=str(pathlib.Path(__file__).resolve().parent),
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["gh", "secret", "set", "KAKAO_REFRESH_TOKEN"],
            input=refresh_token.encode("utf-8"),
            cwd=str(pathlib.Path(__file__).resolve().parent),
            capture_output=True,
            check=False,
        )
        print("✅ GitHub 저장소(thehojunlee/kakao-stock-news)에도 토큰이 자동 등록되었습니다!")
    except Exception:
        pass

    messages = send_stock_news.prepare_messages()
    for msg_text, more_url in messages:
        send_stock_news.send_kakao_memo(access_token, msg_text, more_url)
    print("📱 카카오톡 발송 완료!")


if __name__ == "__main__":
    main()
