import os
import subprocess
import sys
import webbrowser

import send_stock_news


def set_github_secret(secret_name: str, secret_value: str) -> None:
    """gh CLI를 사용해 현재 저장소에 GitHub Actions Secret을 안전하게 등록합니다."""
    proc = subprocess.run(
        ["gh", "secret", "set", secret_name],
        input=secret_value.encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"{secret_name} 등록 실패: {err}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 65)
    print("☁️ GitHub 자동 발송(Secrets) 등록 & AI 요약 즉시 카톡 테스트 도우미")
    print("=" * 65)

    rest_api_key = input("\n👉 1. [KAKAO_REST_API_KEY] (32자리 REST API 키) 붙여넣기: ").strip()
    refresh_token = input("👉 2. [KAKAO_REFRESH_TOKEN] (아까 발급받은 리프레시 토큰) 붙여넣기: ").strip()

    if not rest_api_key or not refresh_token:
        print("[오류] 카카오 REST API 키와 Refresh Token은 필수입니다.")
        sys.exit(1)

    print("\n" + "-" * 65)
    print("🤖 [AI 요약용 무료 Gemini API 키 안내]")
    print("구글 AI 스튜디오(https://aistudio.google.com/app/apikey)에서")
    print("[Create API key] 버튼만 누르면 무료로 AI 요약 키(AIza...로 시작)가 발급됩니다.")
    open_browser = input("👉 지금 구글 AI 키 발급 페이지를 브라우저로 열까요? (y/Enter=열기, n=이미 있음): ").strip().lower()
    if open_browser in ("", "y", "yes"):
        webbrowser.open("https://aistudio.google.com/app/apikey")

    gemini_key = input("\n👉 3. 발급받은 [GEMINI_API_KEY] 붙여넣기 (건너뛰려면 Enter): ").strip()

    print("\n⏳ GitHub 비공개 저장소에 암호화된 Secret으로 등록 중입니다...")
    try:
        set_github_secret("KAKAO_REST_API_KEY", rest_api_key)
        print("  ✓ KAKAO_REST_API_KEY 등록 완료")
        set_github_secret("KAKAO_REFRESH_TOKEN", refresh_token)
        print("  ✓ KAKAO_REFRESH_TOKEN 등록 완료")
        if gemini_key:
            set_github_secret("GEMINI_API_KEY", gemini_key)
            print("  ✓ GEMINI_API_KEY 등록 완료")
    except Exception as e:
        print(f"[오류] GitHub Secret 등록 중 문제 발생: {e}")
        sys.exit(1)

    print("\n🚀 지금 바로 4대 뉴스(네이버·구글·인베스팅·야후) + AI 요약 카톡을 발송해 봅니다...")
    os.environ["KAKAO_REST_API_KEY"] = rest_api_key
    os.environ["KAKAO_REFRESH_TOKEN"] = refresh_token
    if gemini_key:
        os.environ["GEMINI_API_KEY"] = gemini_key

    try:
        messages = send_stock_news.prepare_messages()
        access_token = send_stock_news.refresh_kakao_access_token(
            rest_api_key=rest_api_key, refresh_token=refresh_token
        )
        print("\n" + "=" * 55)
        for msg_text, more_url in messages:
            print(msg_text)
            print("-" * 55)
            send_stock_news.send_kakao_memo(access_token, msg_text, more_url)
        print("🎉 휴대폰 카카오톡으로 AI 요약 뉴스가 발송되었습니다!")
        print("이제 컴퓨터를 꺼두어도 평일 아침 7시 30분마다 GitHub가 자동으로 카톡을 보냅니다!")
    except Exception as e:
        print(f"[오류] 테스트 발송 중 오류 발생: {e}")


if __name__ == "__main__":
    main()
