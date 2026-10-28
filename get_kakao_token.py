import http.server
import sys
import urllib.parse
import webbrowser

import send_stock_news

REDIRECT_URI = "http://localhost:5000/oauth"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


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
                "<h2>✅ 카카오 인증이 완료되었습니다!</h2>"
                "<p>이 브라우저 창을 닫고, 처음에 열었던 검은색 실행 창을 확인해주세요.</p>"
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

    print("=" * 65)
    print("카카오톡 '나에게 보내기' 초기 토큰 발급 & 즉시 발송 테스트 도우미")
    print("=" * 65)
    print(
        "\n[시작 전 카카오 개발자 사이트(최신 개편 화면) 설정 확인]\n"
        "1. 왼쪽 메뉴 [카카오 로그인] > [일반] -> '활성화 설정'을 [ON]으로 변경\n"
        "2. 왼쪽 메뉴 [앱] > [플랫폼 키] -> [REST API 키] 클릭 ->\n"
        f"   하단 '카카오 로그인 리다이렉트 URI'에 {REDIRECT_URI} 등록\n"
        "   하단 '클라이언트 시크릿(Client Secret)'은 [사용 안함]으로 설정\n"
        "3. 왼쪽 메뉴 [앱] > [제품 링크 관리] -> '웹 도메인'에\n"
        "   https://finance.naver.com 등록\n"
        "4. 왼쪽 메뉴 [카카오 로그인] > [동의항목] ->\n"
        "   맨 아래 '카카오톡 메시지 전송(talk_message)'을 [선택 동의]로 설정\n"
    )

    rest_api_key = input("👉 1단계: 카카오 앱의 [REST API 키]를 붙여넣고 Enter를 누르세요: ").strip()
    if not rest_api_key:
        print("[오류] REST API 키가 입력되지 않았습니다.")
        sys.exit(1)

    client_secret = input(
        "👉 2단계: Client Secret을 별도로 켠 경우에만 입력 (안 켰으면 그냥 Enter): "
    ).strip()

    auth_url = (
        f"https://kauth.kakao.com/oauth/authorize?"
        f"client_id={rest_api_key}&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code&scope=talk_message"
    )

    print("\n" + "-" * 65)
    print("🌐 잠시 후 인터넷 브라우저가 자동으로 열립니다.")
    print("카카오 로그인 후 [전체 동의하기] -> [동의하고 계속하기]를 눌러주세요!")
    print("(만약 브라우저가 안 열리면 아래 주소를 직접 브라우저에 붙여넣으세요)")
    print(f"\n{auth_url}\n")
    print("-" * 65)

    webbrowser.open(auth_url)

    auth_code = None
    try:
        server = http.server.HTTPServer(("localhost", 5000), OAuthCallbackHandler)
        print("⏳ 브라우저에서 [동의하고 계속하기]를 누를 때까지 대기 중입니다...")
        while OAuthCallbackHandler.auth_code is None:
            server.handle_request()
        auth_code = OAuthCallbackHandler.auth_code
        server.server_close()
    except OSError:
        print("\n[수동 입력 모드] 브라우저에서 동의 후 이동된 주소창의 URL 전체를 붙여넣어 주세요.")
        raw_url = input("👉 주소창 URL 붙여넣기: ").strip()
        parsed = urllib.parse.urlparse(raw_url)
        qs = urllib.parse.parse_qs(parsed.query)
        auth_code = qs.get("code", [raw_url])[0]

    payload = {
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": REDIRECT_URI,
        "code": auth_code,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    try:
        token_data = send_stock_news.http_post_form(TOKEN_URL, payload)
    except RuntimeError as e:
        print(f"\n[오류] 토큰 발급 실패: {e}")
        sys.exit(1)

    refresh_token = token_data.get("refresh_token", "")
    access_token = token_data.get("access_token", "")

    print("\n✅ 토큰 발급 성공! 지금 바로 내 카카오톡으로 첫 테스트 뉴스를 보내봅니다...")
    try:
        messages = send_stock_news.prepare_messages()
        for msg_text, more_url in messages:
            send_stock_news.send_kakao_memo(access_token, msg_text, more_url)
        print("📱 카톡 도착! 지금 휴대폰 카카오톡 '나와의 채팅방'을 확인해보세요!")
    except Exception as e:
        print(f"[경고] 테스트 메시지 발송 중 오류 발생: {e}")

    print("\n" + "=" * 65)
    print("🔑 아래 2개 값을 메모장에 잠시 복사해 두세요 (3_setup_github.bat에서 사용)")
    print("=" * 65)
    print("1) 이름(Name): KAKAO_REST_API_KEY")
    print(f"   값(Secret): {rest_api_key}\n")
    print("2) 이름(Name): KAKAO_REFRESH_TOKEN")
    print(f"   값(Secret): {refresh_token}")
    if client_secret:
        print("\n3) 이름(Name): KAKAO_CLIENT_SECRET")
        print(f"   값(Secret): {client_secret}")
    print("=" * 65)


if __name__ == "__main__":
    main()
