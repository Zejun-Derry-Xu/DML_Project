"""Restore a backup ONLY into a new _restore_test database. Never overwrite/drop a database."""

import argparse
import re
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"returnflow_[a-z0-9_]+_restore_test", args.database):
        parser.error("Use a NEW database named returnflow_<unique_name>_restore_test")
    compose = [
        "docker",
        "compose",
        "--env-file",
        ".env",
        "--env-file",
        ".release.env",
        "-f",
        "compose.jetstream.yml",
        "exec",
        "-T",
        "db",
    ]
    # createdb refuses an existing database; there is intentionally no drop/clean option.
    subprocess.run(compose + ["createdb", "-U", "returnflow", args.database], check=True)
    with args.backup.open("rb") as stream:
        subprocess.run(
            compose
            + [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "-U",
                "returnflow",
                "-d",
                args.database,
            ],
            stdin=stream,
            check=True,
        )
    subprocess.run(
        compose
        + [
            "psql",
            "-U",
            "returnflow",
            "-d",
            args.database,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "SELECT count(*) FROM return_cases; SELECT count(*) FROM return_requests;",
        ],
        check=True,
    )
    print(
        "Restore verified in isolated test database. "
        "Live database was not changed; test copy retained."
    )


if __name__ == "__main__":
    main()
