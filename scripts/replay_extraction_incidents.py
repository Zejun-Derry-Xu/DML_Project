"""Replay the four observed deployment examples; regression evidence, NOT held-out data."""

import asyncio
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.domain.models import ReturnCase
from app.extractors.hybrid import HybridExtractor
from app.extractors.ollama import OllamaExtractor

EXAMPLES = [
    ("I have not used it.", False),
    ("I never wore this shirt.", False),
    ("It has stayed in my closet with the tags attached; I haven't worn it.", False),
    ("I wore it yesterday.", True),
]


async def main():
    results = []
    for mode in ("model", "hybrid"):
        provider = OllamaExtractor(
            base_url="http://127.0.0.1:11434/v1", model="qwen3:4b", timeout_seconds=60, retries=0
        )
        extractor = HybridExtractor(provider) if mode == "hybrid" else provider
        for text, expected in EXAMPLES:
            started = perf_counter()
            facts = await extractor.extract(
                text, ReturnCase(session_id=uuid4(), item_category="apparel"), "used"
            )
            results.append(
                {
                    "mode": mode,
                    "text": text,
                    "expected_used": expected,
                    "used": facts.used,
                    "passed": facts.used == expected,
                    "path": getattr(extractor, "last_path", "model"),
                    "seconds": perf_counter() - started,
                }
            )
    report = {
        "kind": "known incident regressions, not independent generalization evidence",
        "results": results,
        "passed": sum(row["passed"] for row in results),
    }
    target = Path(__file__).parents[1] / "docs/results/reliability-incidents.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
