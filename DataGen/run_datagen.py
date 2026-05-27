#!/usr/bin/env python3
"""Run the full DataGen pipeline: generate → convert → upload/localdb.

Usage:
  uv run python run_datagen.py             # respects USE_DATASTORE in .env
  uv run python run_datagen.py --firestore # force Firestore upload
  uv run python run_datagen.py --sqlite    # force local SQLite
"""
import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ENV_PATH = SCRIPT_DIR.parent / "ADKAgents" / "bank_agent" / ".env"


def run(script: str) -> None:
    result = subprocess.run([sys.executable, SCRIPT_DIR / script])
    if result.returncode != 0:
        print(f"Failed at {script}")
        sys.exit(result.returncode)


def _env_use_datastore() -> bool:
    if not ENV_PATH.exists():
        return False
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith("USE_DATASTORE="):
            return line.split("=", 1)[1].strip().lower() == "true"
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full DataGen pipeline.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--firestore", action="store_true", help="Upload to Firestore (overrides .env)")
    group.add_argument("--sqlite", action="store_true", help="Create local SQLite DB (overrides .env)")
    args = parser.parse_args()

    use_firestore = args.firestore or (not args.sqlite and _env_use_datastore())

    print("Step 1/3: Generating synthetic data...")
    run("dataFakeGen.py")
    print("Step 2/3: Preparing NoSQL documents...")
    run("prepare_for_nosql.py")
    if use_firestore:
        print("Step 3/3: Uploading to Firestore...")
        run("upload_to_datestore.py")
    else:
        print("Step 3/3: Creating local SQLite database...")
        run("localdb_setup.py")
    print("Done!")


if __name__ == "__main__":
    main()
