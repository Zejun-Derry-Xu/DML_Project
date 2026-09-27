"""Select and conservatively annotate an ABCD return-related pilot.

The official compressed corpus is an input, never a repository artifact. Output
contains source utterances and must stay under the ignored data/abcd_pilot path.
"""

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SUBFLOWS = ("return_size", "return_color", "return_stain", "refund_initiate")
QUOTAS = {"train": 8, "dev": 1, "test": 1}
REQUEST = re.compile(r"\b(return|refund|send\s+back)\b", re.I)
REASONS = (
    (
        "does_not_fit",
        re.compile(r"wrong size|does(?:n't| not) fit|too (?:small|large|tight)|\bsnug\b", re.I),
    ),
    ("defective", re.compile(r"\bstain(?:ed)?\b|\bdefect(?:ive)?\b|\bbroken\b", re.I)),
    ("changed_mind", re.compile(r"no longer want|changed my mind|don't want it anymore", re.I)),
)


def evidence(value: str, text: str, match: re.Match[str]) -> dict[str, Any]:
    return {
        "value": value,
        "quote": match.group(),
        "start": match.start(),
        "end": match.end(),
        "source": "customer_utterance",
    }


def annotate(text: str, scenario: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    fields: dict[str, Any] = {}
    reasons: list[str] = []
    request = REQUEST.search(text)
    if request:
        fields["intent"] = evidence("return", text, request)
    order_id = str(scenario.get("order", {}).get("order_id", ""))
    if order_id:
        match = re.search(r"(?<!\w)" + re.escape(order_id) + r"(?!\w)", text)
        if match:
            fields["order_id"] = evidence(order_id, text, match)
    for name in scenario.get("product", {}).get("names", []):
        match = re.search(
            r"(?<!\w)" + re.escape(name).replace(r"\ ", r"\s+") + r"(?!\w)", text, re.I
        )
        if match:
            fields["item_name"] = evidence(name, text, match)
            break
    matches = [(value, pattern.search(text)) for value, pattern in REASONS]
    matches = [(value, match) for value, match in matches if match]
    if len(matches) == 1:
        value, match = matches[0]
        assert match is not None
        fields["reason"] = evidence(value, text, match)
    elif len(matches) > 1:
        reasons.append("conflicting_reason_phrases")
    if re.search(r"wrong colou?r|colou?r is wrong", text, re.I):
        reasons.append("reason_outside_returnflow_taxonomy")
    if not request:
        reasons.append("no_explicit_return_request_in_selected_turn")
    if "order_id" not in fields:
        reasons.append("order_id_not_stated_in_selected_turn")
    return fields, reasons


def build_pilot(corpus: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for subflow in SUBFLOWS:
        for split, quota in QUOTAS.items():
            candidates = sorted(
                (c for c in corpus[split] if c["scenario"]["subflow"] == subflow),
                key=lambda c: c["convo_id"],
            )
            for conversation in candidates[:quota]:
                turns = conversation["original"]
                selected = next(
                    (
                        (i, text)
                        for i, (role, text) in enumerate(turns)
                        if role == "customer" and REQUEST.search(text)
                    ),
                    None,
                )
                if selected is None:
                    rows.append(
                        {
                            "split": split,
                            "convo_id": conversation["convo_id"],
                            "subflow": subflow,
                            "status": "excluded",
                            "reasons": ["no_explicit_return_request"],
                        }
                    )
                    continue
                turn_index, text = selected
                fields, reasons = annotate(text, conversation["scenario"])
                if subflow == "refund_initiate":
                    reasons.append("refund_before_return_scope_mismatch")
                rows.append(
                    {
                        "split": split,
                        "convo_id": conversation["convo_id"],
                        "subflow": subflow,
                        "turn_index": turn_index,
                        "text": text,
                        "fields": fields,
                        "status": "out_of_scope"
                        if subflow == "refund_initiate"
                        else ("review" if reasons else "auto_usable"),
                        "reasons": reasons,
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="Path to official abcd_v1.1.json.gz")
    parser.add_argument("--output", type=Path, default=Path("data/abcd_pilot/pilot.json"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("docs/results/abcd-pilot-manifest.json")
    )
    args = parser.parse_args()
    with gzip.open(args.corpus, "rt", encoding="utf-8") as source:
        corpus = json.load(source)
    rows = build_pilot(corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
    manifest = {
        "source": "asappresearch/abcd data/abcd_v1.1.json.gz",
        "source_revision": "6b8700ce67c6b37b062dd7a60abc76d7ef832a97",
        "source_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        "selection": "lowest convo_id per subflow and original split; 8 train, 1 dev, 1 test",
        "rows": [
            {
                "split": row["split"],
                "convo_id": row["convo_id"],
                "subflow": row["subflow"],
                "turn_index": row.get("turn_index"),
                "status": row["status"],
                "reasons": row["reasons"],
            }
            for row in rows
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "total": len(rows),
                "status": Counter(row["status"] for row in rows),
                "split": Counter(row["split"] for row in rows),
                "reason": Counter(reason for row in rows for reason in row["reasons"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
