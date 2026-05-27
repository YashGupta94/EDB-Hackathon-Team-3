from google.cloud import firestore
import os
import json
from pathlib import Path

SCRIPT_DIR: Path = Path(__file__).parent
DOCUMENTS_DIR: Path = SCRIPT_DIR / "documents"
_ENV_PATH: Path = SCRIPT_DIR.parent / "ADKAgents" / "bank_agent" / ".env"


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env(_ENV_PATH)


def upload_to_gcp():
    files = list(DOCUMENTS_DIR.glob("*.json"))
    if not files:
        print("Warning: No JSON files found in documents/. Did you run prepare_for_nosql.py first?")
        return

    db = firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT"))

    for file in files:
        print(f"uploading file {file.name}")
        content: dict = json.loads(file.read_text())

        doc_ref = db.collection("customers").document(file.stem)
        doc_ref.set(content)


if __name__ == "__main__":
    upload_to_gcp()

