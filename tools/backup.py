"""Timestamped, rotating backup of all FAIR review data.

Copies the parts/ tree, the quality clauses, and the audit log into a dated
ZIP under the backup directory, then prunes old backups beyond KEEP_COUNT.

Run manually:   python tools/backup.py
Or on a schedule (see tools/install_backup_task.ps1).

By default backups go to a `Backups` folder NEXT TO the project. For real
durability, point BACKUP_DIR at a second physical disk or a company-approved
backup location (set the FAIR_BACKUP_DIR environment variable).
"""
from __future__ import annotations

import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_DIR = ROOT.parent / "FAIR_Backups"
BACKUP_DIR = Path(os.environ.get("FAIR_BACKUP_DIR", str(DEFAULT_BACKUP_DIR)))
KEEP_COUNT = 30  # keep the most recent N backups

INCLUDE = ["parts", "Skyryse Quality Clauses.md", "audit.log"]


def make_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    dest = BACKUP_DIR / f"fair_backup_{stamp}.zip"

    file_count = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in INCLUDE:
            path = ROOT / item
            if path.is_file():
                zf.write(path, path.name)
                file_count += 1
            elif path.is_dir():
                for f in path.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(ROOT))
                        file_count += 1
    return dest, file_count


def prune() -> int:
    backups = sorted(BACKUP_DIR.glob("fair_backup_*.zip"))
    removed = 0
    while len(backups) > KEEP_COUNT:
        old = backups.pop(0)
        old.unlink()
        removed += 1
    return removed


if __name__ == "__main__":
    dest, n = make_backup()
    removed = prune()
    size_kb = dest.stat().st_size / 1024
    print(f"Backed up {n} files -> {dest} ({size_kb:.0f} KB)")
    if removed:
        print(f"Pruned {removed} old backup(s); keeping last {KEEP_COUNT}.")
