"""Optional direct Groq diagnostic; never routes through the local gateway."""

import os
import sys

from dotenv import load_dotenv

from .config import DEFAULT_ENV_FILE


def main() -> int:
    load_dotenv(DEFAULT_ENV_FILE, override=False)
    if not os.getenv("GROQ_API_KEY"):
        print("Set GROQ_API_KEY in p5_inferencing/.env.", file=sys.stderr)
        return 1
    try:
        from groq import Groq
    except ImportError:
        print("Install p5_inferencing/requirements-groq.txt first.", file=sys.stderr)
        return 1
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    with Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=0) as client:
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with exactly: Groq connection works"}],
                temperature=1,
                max_completion_tokens=128,
                top_p=1,
                reasoning_effort="medium",
                stream=True,
            )
            print(f"Streaming diagnostic from {model}:")
            for chunk in completion:
                if chunk.choices and chunk.choices[0].delta.content:
                    print(chunk.choices[0].delta.content, end="", flush=True)
        except Exception as exc:
            print(f"Groq diagnostic failed ({type(exc).__name__}).", file=sys.stderr)
            return 1
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
