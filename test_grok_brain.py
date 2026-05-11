"""Smoke-test Grok Brain without printing secrets."""

from dotenv import load_dotenv

load_dotenv()

from modules.grok_brain import get_brain_status, test_connection


if __name__ == "__main__":
    status = get_brain_status()
    print("=== Grok Brain Status ===")
    print(f"Enabled: {status['enabled']}")
    print(f"Configured: {status['configured']}")
    print(f"Model: {status['model']}")
    print(f"Daily calls: {status['daily_calls']}/{status['max_daily_calls']}")

    if not status["configured"]:
        print("XAI_API_KEY is not set in .env")
        raise SystemExit(1)

    result = test_connection()
    print("\n=== Connection Test ===")
    print(f"OK: {result.get('ok', False)}")
    if result.get("ok"):
        print(f"Verdict: {result.get('verdict', 'reviewed')}")
        print(f"Risk: {result.get('risk_level', 'unknown')}")
        print(f"Review: {result.get('brief_review', '')}")
    else:
        print(f"Reason: {result.get('reason') or result.get('error', 'unknown')}")
        raise SystemExit(1)
