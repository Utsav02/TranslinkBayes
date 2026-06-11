"""
Downloads the latest TransLink static GTFS and refreshes the DB if it changed.

Uses HTTP If-Modified-Since to avoid re-downloading the 39 MB zip when
TransLink hasn't published a new schedule. Supersedes check_gtfs_changes.py.

Run weekly (launchd / cron) or on-demand:
    python sync_static_gtfs.py           # skip if not modified
    python sync_static_gtfs.py --force   # download regardless
"""
import argparse
import hashlib
import io
import json
import logging
import shutil
import subprocess
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from config import DB_STATIC, LOG_DIR, ROOT

# ── Paths ─────────────────────────────────────────────────────────────────────
GTFS_URL      = "https://gtfs-static.translink.ca/gtfs/google_transit.zip"
ACTIVE_DIR    = ROOT / "data" / "gtfs_static"        # what process_static.py reads
ARCHIVE_DIR   = ROOT / "data" / "static_archive"
SNAPSHOT_DIR  = ROOT / "data" / "static"             # dated extracts kept for reference
META_FILE     = ROOT / "database" / "gtfs_static_meta.json"
PROCESS_SCRIPT = ROOT / "pipeline" / "process_static.py"

KEY_FILES = ["stop_times.txt", "trips.txt", "routes.txt", "stops.txt"]

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "sync_static_gtfs.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ── Metadata helpers ──────────────────────────────────────────────────────────

def _load_meta() -> dict:
    if META_FILE.exists():
        return json.loads(META_FILE.read_text())
    return {}


def _save_meta(meta: dict) -> None:
    META_FILE.write_text(json.dumps(meta, indent=2))


# ── Hash helpers ──────────────────────────────────────────────────────────────

def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _folder_hashes(folder: Path) -> dict[str, str]:
    return {
        name: _hash_file(folder / name)
        for name in KEY_FILES
        if (folder / name).exists()
    }


# ── Download ──────────────────────────────────────────────────────────────────

def _is_modified_since(last_modified: str | None) -> bool:
    """HEAD request — returns True if the remote file is newer."""
    headers = {}
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        r = requests.head(GTFS_URL, headers=headers, timeout=10)
        if r.status_code == 304:
            logging.info("Remote GTFS not modified (304)")
            return False
        return True
    except requests.RequestException as e:
        logging.warning("HEAD request failed: %s — assuming modified", e)
        return True


def _download_zip() -> tuple[bytes, str | None]:
    """Downloads the zip and returns (content, Last-Modified header value)."""
    logging.info("Downloading %s", GTFS_URL)
    r = requests.get(GTFS_URL, timeout=120)
    r.raise_for_status()
    last_modified = r.headers.get("Last-Modified")
    logging.info("Downloaded %d bytes  Last-Modified: %s", len(r.content), last_modified)
    return r.content, last_modified


# ── Filesystem operations ─────────────────────────────────────────────────────

def _extract_to_snapshot(content: bytes) -> Path:
    """Extracts zip into data/static/YYYY-MM-DD/ and returns that path."""
    dest = SNAPSHOT_DIR / date.today().isoformat()
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        z.extractall(dest)
    logging.info("Extracted to %s", dest)
    return dest


def _archive_active() -> None:
    """Moves data/gtfs_static/ into data/static_archive/GTFS_YYYY-MM-DD/."""
    if not ACTIVE_DIR.exists():
        return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / f"GTFS_{date.today().isoformat()}"
    shutil.move(str(ACTIVE_DIR), dest)
    ACTIVE_DIR.mkdir()
    logging.info("Archived active GTFS → %s", dest)


def _promote_snapshot(snapshot: Path) -> None:
    """Copies snapshot files into data/gtfs_static/."""
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    for f in snapshot.iterdir():
        shutil.copy2(f, ACTIVE_DIR / f.name)
    logging.info("Promoted %s → %s", snapshot, ACTIVE_DIR)


def _run_process_static() -> None:
    """Refreshes gtfs_static.db from the active GTFS files."""
    logging.info("Running process_static.py")
    result = subprocess.run(
        [sys.executable, str(PROCESS_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logging.error("process_static.py failed:\n%s", result.stderr)
        raise RuntimeError(f"process_static.py failed: {result.stderr}")
    logging.info("process_static.py output: %s", result.stdout.strip())


# ── Main ──────────────────────────────────────────────────────────────────────

def sync(force: bool = False) -> bool:
    """
    Returns True if the static GTFS was updated, False if already current.
    """
    meta = _load_meta()

    if not force and not _is_modified_since(meta.get("last_modified")):
        print("Static GTFS is already current — nothing to do.")
        return False

    content, last_modified = _download_zip()
    snapshot = _extract_to_snapshot(content)

    # Hash check: even if Last-Modified changed, content may be identical
    new_hashes = _folder_hashes(snapshot)
    old_hashes = meta.get("hashes", {})

    changed_files = [f for f, h in new_hashes.items() if old_hashes.get(f) != h]
    if not changed_files and not force:
        logging.info("Hashes unchanged despite new Last-Modified — skipping DB update")
        print("Downloaded but content is unchanged — skipping DB update.")
        _save_meta({**meta, "last_modified": last_modified})
        return False

    if changed_files:
        logging.info("Changed files: %s", changed_files)
        print(f"Changes detected in: {', '.join(changed_files)}")

    _archive_active()
    _promote_snapshot(snapshot)
    _run_process_static()

    _save_meta({
        "last_modified":  last_modified,
        "last_downloaded": datetime.now(timezone.utc).isoformat(),
        "hashes":          new_hashes,
        "changed_files":   changed_files,
    })

    print(f"Static GTFS updated. Changed: {', '.join(changed_files) or 'forced'}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync TransLink static GTFS")
    parser.add_argument("--force", action="store_true",
                        help="Download and update even if Last-Modified is unchanged")
    args = parser.parse_args()
    sync(force=args.force)
