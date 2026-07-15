import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def main() -> None:
    load_dotenv(dotenv_path=ENV_FILE)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("CLAUDE_MODEL")

    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is missing.")

    if not model:
        raise RuntimeError("CLAUDE_MODEL is missing.")

    client = Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=100,
        messages=[
            {
                "role": "user",
                "content": (
                    "Reply with exactly this sentence and nothing else: "
                    "Claude API connection successful."
                ),
            }
        ],
    )

    print("=== Claude Response ===")

    for block in response.content:
        if block.type == "text":
            print(block.text)


if __name__ == "__main__":
    main()
