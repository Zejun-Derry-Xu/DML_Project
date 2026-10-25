"""Create a paired-image release manifest after CI has tested and pushed those images."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from app.policy.apparel import VERSION

ROOT = Path(__file__).resolve().parents[1]
DIGEST_IMAGE = re.compile(r"ghcr\.io/[a-z0-9_./-]+@sha256:[a-f0-9]{64}\Z")


def manifest(
    commit: str, api: str, frontend: str, sequence: int = 1, model: str = "qwen3:4b"
) -> dict[str, object]:
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("A complete immutable commit is required")
    if not DIGEST_IMAGE.fullmatch(api) or not DIGEST_IMAGE.fullmatch(frontend):
        raise ValueError("Both images must be GHCR immutable digest references")
    if type(sequence) is not int or sequence < 1:
        raise ValueError("Release sequence must be a positive CI run number")
    return {
        "format": 1,
        "commit": commit,
        "sequence": sequence,
        "api_image": api,
        "frontend_image": frontend,
        "schema": "0004",
        "workflow": "apparel",
        "policy_version": VERSION,
        "policy_sha256": hashlib.sha256(
            (ROOT / f"app/policy/{VERSION}.json").read_bytes()
        ).hexdigest(),
        "model_name": model,
        "model_qualified": False,
        "compatible_rollbacks": [],
        "note": "CI validates guided HTTP/image behavior, not Qwen or Jetstream CPU performance.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="qwen3:4b")
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            manifest(args.commit, args.api, args.frontend, args.sequence, args.model), indent=2
        )
        + "\n"
    )
