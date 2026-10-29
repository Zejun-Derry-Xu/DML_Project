"""Opt-in live Model Studio call. Skips with exit 0 when DASHSCOPE_API_KEY is unset.

Does not send customer text. A successful call only checks that the configured
region accepts the key and returns JSON. It is not an extraction-quality result.
"""

import json
import os
import sys

import httpx

from app.config import Settings
from app.extractors.dashscope import resolved_base_url, resolved_model


def run_smoke(key: str | None = None) -> int:
    secret = (os.environ.get("DASHSCOPE_API_KEY", "") if key is None else key).strip()
    if not secret:
        print("DASHSCOPE_API_KEY is unset; live DashScope smoke skipped.")
        return 0
    settings = Settings(llm_provider="dashscope")
    base = resolved_base_url(settings)
    model = resolved_model(settings)
    payload = {
        "model": model,
        "temperature": 0,
        "stream": False,
        "enable_thinking": False,
        "messages": [
            {
                "role": "user",
                "content": 'Reply with JSON only: {"ok": true}',
            }
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        response = httpx.post(
            base + "/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {secret}"},
            timeout=30,
        )
    except httpx.HTTPError as error:
        print(f"DashScope smoke failed: {type(error).__name__}")
        return 1
    if response.status_code != 200:
        print(f"DashScope smoke failed: HTTP {response.status_code}")
        return 1
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        print("DashScope smoke failed: response was not JSON")
        return 1
    usage = body.get("usage") if isinstance(body, dict) else None
    tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
    print(f"DashScope smoke ok model={model} total_tokens={tokens} ok={parsed.get('ok')}")
    return 0


def main() -> None:
    sys.exit(run_smoke())


if __name__ == "__main__":
    main()
