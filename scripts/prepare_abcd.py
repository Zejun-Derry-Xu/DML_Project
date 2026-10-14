"""Convert the pinned official ABCD corpus, retaining native split membership."""

import argparse
import json
from pathlib import Path

from app.evaluation.abcd import prepare_abcd

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=ROOT / "data/evaluation_sources/abcd/abcd_v1.1.json.gz"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "data/evaluation_runs/abcd/prepared"
    )
    args = parser.parse_args()
    print(json.dumps(prepare_abcd(args.source, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
