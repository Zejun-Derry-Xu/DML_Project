"""Mechanical v3 namespace snapshot; refuse any source other than the verified v3 tree."""

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED = "4281bb8989f6d9bcff75fdd4c54f29dd8f47b9712ad5b007faf9ddb8fa617c3c"


def freeze(root):
    source = root / "app/extractors"
    target = source / "frozen_v3"
    if target.exists():
        raise ValueError("Snapshot already exists; never overwrite")
    files = sorted(p for p in source.rglob("*") if p.suffix in {".py", ".md"})
    digest = hashlib.sha256(b"".join(p.read_bytes() for p in files)).hexdigest()
    if digest != EXPECTED:
        raise ValueError("Not the frozen v3 extractor tree; refusing to snapshot")
    manifest = {
        "source_revision": "a47065a",
        "source_sha256": digest,
        "original_files": {},
        "namespace_only_rewrite": "app.extractors. -> app.extractors.frozen_v3.",
    }
    for path in files:
        relative = path.relative_to(source)
        manifest["original_files"][str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
        if relative.parts[0] == "frozen_v2":
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text()
        if path.suffix == ".py":
            text = text.replace("app.extractors.", "app.extractors.frozen_v3.")
        destination.write_text(text)
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    freeze(parser.parse_args().root.resolve())
