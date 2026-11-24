"""Opt-in live provider smoke test: python test_gemini.py."""
def main():
    from dotenv import load_dotenv
    load_dotenv(override=False)
    from services.gemini_service import stream_chat, ProviderError
    try:
        reply = ''.join(stream_chat([{"role": "user", "content": "Reply with Hello."}]))
        if not reply.strip(): raise RuntimeError("Empty response")
        print("Gemini smoke test passed")
    except ProviderError as exc:
        print(f"Gemini smoke test failed: {exc.code} ({exc.status})")
        raise SystemExit(1) from None

if __name__ == "__main__":
    main()
