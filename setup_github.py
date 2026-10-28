import pathlib
import subprocess
import sys

import send_stock_news

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


def set_github_secret(secret_name: str, secret_value: str) -> None:
    """gh CLI를 사용해 현재 저장소에 GitHub Actions Secret을 안전하게 등록합니다."""
    proc = subprocess.run(
        ["gh", "secret", "set", secret_name],
        input=secret_value.encode("utf-8"),
        cwd=str(pathlib.Path(__file__).resolve().parent),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"{secret_name} 등록 실패: {err}")


def detect_key_type(api_key: str) -> tuple[str, str]:
    """입력된 키의 시작 문자열을 보고 Claude / Gemini / OpenAI를 자동 판별합니다."""
    if api_key.startswith("sk-ant-"):
        return "ANTHROPIC_API_KEY", "Claude (Anthropic)"
    if api_key.startswith("AIza"):
        return "GEMINI_API_KEY", "Gemini (Google AI)"
    if api_key.startswith("sk-"):
        return "OPENAI_API_KEY", "ChatGPT (OpenAI)"
    # 기본값은 Claude 또는 Gemini
    return "ANTHROPIC_API_KEY", "Claude (Anthropic)"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    send_stock_news.load_local_env()

    print("=" * 65)
    print("🤖 AI 요약 키 (Claude / Gemini / OpenAI 자동 인식) 등록 도우미")
    print("=" * 65)
    print("\n• 클로드(Claude) 키: https://console.anthropic.com/settings/keys (sk-ant-... 로 시작)")
    print("• 구글(Gemini) 무료 키: https://aistudio.google.com/app/apikey (AIza... 로 시작)")
    print("• 오픈AI(ChatGPT) 키: https://platform.openai.com/api-keys (sk-... 로 시작)\n")

    raw_key = input("👉 발급받은 AI API 키를 붙여넣고 Enter를 누르세요: ").strip()
    if not raw_key:
        print("[오류] 키가 입력되지 않았습니다.")
        sys.exit(1)

    secret_name, provider_label = detect_key_type(raw_key)
    print(f"\n🔍 감지된 AI 종류: {provider_label} ({secret_name})")

    save_env_key(secret_name, raw_key)
    print("✅ 1/2: 로컬 금고(D:\\FinanceData\\kakao_stock_news.env) 저장 완료!")

    try:
        set_github_secret(secret_name, raw_key)
        print(f"✅ 2/2: GitHub 저장소(thehojunlee/kakao-stock-news)에 {secret_name} 등록 완료!")
        print(f"\n🎉 모든 설정이 끝났습니다! 이제 매일 아침 8시에 {provider_label}가 요약한 리포트가 발송됩니다.")
    except Exception as e:
        print(f"[오류] GitHub 등록 중 문제 발생: {e}")


if __name__ == "__main__":
    main()
