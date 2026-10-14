"""Download pinned public evaluation sources and record hashes without checking in corpora."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRECTORY = ROOT / "data" / "evaluation_sources"
SOURCES: dict[str, dict[str, Any]] = {
    "abcd": {
        "repository": "asappresearch/abcd",
        "revision": "6b8700ce67c6b37b062dd7a60abc76d7ef832a97",
        "license": "MIT (upstream LICENSE)",
        "files": {
            "abcd_v1.1.json.gz": "data/abcd_v1.1.json.gz",
            "abcd_sample.json": "data/abcd_sample.json",
            "guidelines.json": "data/guidelines.json",
            "LICENSE": "LICENSE",
        },
    },
    "or_sharc": {
        "repository": "Yifan-Gao/open_retrieval_conversational_machine_reading",
        "revision": "309c4ea3a7cc4c7a815d7f46292d91fc9a0de581",
        "license": "CC BY-SA 3.0 (upstream README)",
        "files": {
            "id2snippet.json": "data/id2snippet.json",
            "open_retrieval_sharc_train.json": "data/open_retrieval_sharc_train.json",
            "open_retrieval_sharc_dev.json": "data/open_retrieval_sharc_dev.json",
            "open_retrieval_sharc_test.json": "data/open_retrieval_sharc_test.json",
            "README.md": "README.md",
        },
    },
    "tau2": {
        "repository": "sierra-research/tau2-bench",
        "revision": "dd8757d4c8791dad7b3cdaf02a105a3d5f9d86bd",
        "license": "MIT (upstream LICENSE)",
        "files": {
            "tasks.json": "data/tau2/domains/retail/tasks.json",
            "db.json": "data/tau2/domains/retail/db.json",
            "policy.md": "data/tau2/domains/retail/policy.md",
            "split_tasks.json": "data/tau2/domains/retail/split_tasks.json",
            "LICENSE": "LICENSE",
        },
    },
}


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def fetch_dataset(name: str, directory: Path, client: httpx.Client) -> dict[str, Any]:
    source = SOURCES[name]
    target = directory / name
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / "manifest.json"
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    files = []
    for filename, upstream_path in source["files"].items():
        url = (
            f"https://raw.githubusercontent.com/{source['repository']}/"
            f"{source['revision']}/{upstream_path}"
        )
        destination = target / filename
        previous = next(
            (entry for entry in existing.get("files", []) if entry["name"] == filename), None
        )
        verified = (
            destination.exists() and previous is not None
            and previous["url"] == url and previous["sha256"] == sha256(destination)
        )
        if not verified:
            partial = destination.with_name(destination.name + ".partial")
            try:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with partial.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
        files.append(
            {"name": filename, "url": url, "sha256": sha256(destination),
             "bytes": destination.stat().st_size}
        )
    manifest = {
        "dataset": name, "repository": source["repository"],
        "revision": source["revision"], "license": source["license"],
        "verified_at": datetime.now(UTC).isoformat(), "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=(*SOURCES, "all"), default="all")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--manifest-output", type=Path)
    args = parser.parse_args()
    names = list(SOURCES) if args.dataset == "all" else [args.dataset]
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        manifests = [fetch_dataset(name, args.directory, client) for name in names]
    report = {"sources": manifests}
    if args.manifest_output:
        args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"datasets": [{"name": entry["dataset"], "revision": entry["revision"],
                                  "files": len(entry["files"])} for entry in manifests]}, indent=2))


if __name__ == "__main__":
    main()
