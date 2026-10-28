import os
import pathlib
import subprocess
import sys
import webbrowser

import send_stock_news

EXTERNAL_ENV_FILE = pathlib.Path(r"D:\FinanceData\kakao_stock_news.env")


def save_local_env(env_dict: dict[str, str]) -> None:
    """볼트 밖(D:\\FinanceData\\kakao_stock_news.env)에 키를 보관하여 재입력을 방지합니다."""
    EXTERNAL_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in env_dict.items() if v]
    EXTERNAL_ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    send_stock_news.load_local_env()
    saved_rest = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    saved_refresh = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    saved_gemini = os.environ.get("GEMINI_API_KEY", "").strip()

    print("=" * 65)
    print("☁️ AI 요약 키(Gemini) & GitHub 자동 발송 등록 도우미")
    print("=" * 65)

    if saved_rest:
        inp_rest = input(
            "👉 1. [KAKAO_REST_API_KEY] (이미 저장됨, 그대로 쓰려면 Enter): "
        ).strip()
        rest_api_key = inp_rest or saved_rest
    else:
        rest_api_key = input(
            "\n👉 1. [KAKAO_REST_API_KEY] (32자리 REST API 키) 붙여넣기: "
        ).strip()

    if saved_refresh:
        inp_refresh = input(
            "👉 2. [KAKAO_REFRESH_TOKEN] (이미 저장됨, 그대로 쓰려면 Enter): "
        ).strip()
        refresh_token = inp_refresh or saved_refresh
    else:
        refresh_token = input(
            "👉 2. [KAKAO_REFRESH_TOKEN] (아까 발급받은 리프레시 토큰) 붙여넣기: "
        ).strip()

    if not rest_api_key or not refresh_token:
        print("[오류] 카카오 REST API 키와 Refresh Token은 필수입니다.")
        sys.exit(1)

    print("\n" + "-" * 65)
    print("🤖 [AI 요약용 무료 Gemini API 키 발급 안내]")
    print("구글 AI 스튜디오(https://aistudio.google.com/app/apikey)에서")
    print("우측 상단 [Create API key] 버튼만 누르면 무료 AI 키(AIza...로 시작)가 발급됩니다!")
    if not saved_gemini:
        open_browser = (
            input(
                "👉 지금 구글 AI 키 발급 페이지를 브라우저로 열까요? (Enter=열기, n=이미 복사함): "
            )
            .strip()
            .lower()
        )
        if open_browser in ("", "y", "yes"):
            webbrowser.open("https://aistudio.google.com/app/apikey")

    if saved_gemini:
        inp_gemini = input(
            "👉 3. [GEMINI_API_KEY] (이미 저장됨, 그대로 쓰려면 Enter): "
        ).strip()
        gemini_key = inp_gemini or saved_gemini
    else:
        gemini_key = input(
            "\n👉 3. 발급받은 [GEMINI_API_KEY] (AIza...로 시작) 붙여넣기: "
        ).strip()

    save_local_env(
        {
            "KAKAO_REST_API_KEY": rest_api_key,
            "KAKAO_REFRESH_TOKEN": refresh_token,
            "GEMINI_API_KEY": gemini_key,
        }
    )
    print("  ✓ 로컬 금고(D:\\FinanceData\\kakao_stock_news.env)에 안전하게 저장되었습니다.")

    print("\n⏳ GitHub 비공개 저장소(thehojunlee/kakao-stock-news)에 Secret 등록 중...")
    try:
        set_github_secret("KAKAO_REST_API_KEY", rest_api_key)
        print("  ✓ KAKAO_REST_API_KEY 등록 완료")
        set_github_secret("KAKAO_REFRESH_TOKEN", refresh_token)
        print("  ✓ KAKAO_REFRESH_TOKEN 등록 완료")
        if gemini_key:
            set_github_secret("GEMINI_API_KEY", gemini_key)
            print("  ✓ GEMINI_API_KEY 등록 완료")
    except Exception as e:
        print(f"[경고] GitHub Secret 등록 중 문제 발생: {e}")

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
    except Exception as e:
        print(f"[오류] 테스트 발송 중 오류 발생: {e}")


if __name__ == "__main__":
    main()
