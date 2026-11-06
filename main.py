"""Watchtower end-to-end orchestration: collect -> filter -> System 1 -> System 2 -> consolidate -> outputs."""
from __future__ import annotations
import argparse, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path
from typing import Any

import run_llm
import build_system2_queue
import run_system2
from storage.database import DB_PATH, init_database
from storage.llm_audit_repository import initialize_audit
from processing.consolidation import consolidate
from generate_digest import generate_digest
from export_classifications import export_classifications

BASE_DIR=Path(__file__).resolve().parent
OUTPUTS_DIR=BASE_DIR/"outputs"
BACKUPS_DIR=BASE_DIR/"storage"/"backups"

def timestamp(): return datetime.now().strftime("%Y%m%d_%H%M%S")

def run_command(label: str, command: list[str]) -> None:
    print(f"\n{'='*78}\n{label}\n{'='*78}\n$ {' '.join(command)}")
    subprocess.run(command,cwd=BASE_DIR,check=True)

def ensure_database():
    init_database(); initialize_audit()

def backup_and_reset_database(stamp: str):
    backup=None
    if DB_PATH.exists():
        BACKUPS_DIR.mkdir(parents=True,exist_ok=True)
        backup=BACKUPS_DIR/f"watchtower_{stamp}.db"
        if backup.exists(): raise FileExistsError(backup)
        shutil.copy2(DB_PATH,backup); DB_PATH.unlink()
    ensure_database()
    return backup

def build_parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fresh",action="store_true",help="Back up and recreate the database.")
    p.add_argument("--skip-collect",action="store_true",help="Skip RSS collection; continue with articles already stored in the database.")
    p.add_argument("--skip-system1", "--skip-llm", dest="skip_system1", action="store_true",
                   help="Skip JEV08 System 1; refresh the queue and reuse any persisted predictions.")
    p.add_argument("--llm-limit",type=int,default=None,help="Maximum System 1 articles this run.")
    p.add_argument("--skip-system2",action="store_true",help="Do not execute LFM2.5; retain routed articles as pending.")
    p.add_argument("--system2-limit",type=int,default=10,help="Maximum System 2 articles this run (default: 10).")
    p.add_argument("--skip-digest",action="store_true",help="Skip Markdown digest and CSV generation.")
    p.add_argument("--output-dir",type=Path,default=None,help="Output folder; must not already exist.")
    return p

def main(argv=None) -> int:
    parser=build_parser(); args=parser.parse_args(argv)
    if args.llm_limit is not None and args.llm_limit<1: parser.error("--llm-limit must be >= 1")
    if args.system2_limit<1: parser.error("--system2-limit must be >= 1")
    stamp=timestamp()
    output_dir=args.output_dir or (OUTPUTS_DIR/f"run_{stamp}")
    if not output_dir.is_absolute(): output_dir=BASE_DIR/output_dir
    try:
        output_dir.mkdir(parents=True,exist_ok=False)
        backup=backup_and_reset_database(stamp) if args.fresh else (ensure_database() or None)
        print(f"Database: {DB_PATH}\nOutput: {output_dir}")
        if args.skip_collect:
            print("\nRSS collection skipped; using articles already stored in the database.")
        else:
            run_command("RSS COLLECTION",[sys.executable,"run_collect.py"])
        run_command("DETERMINISTIC FILTER",[sys.executable,"run_filter.py"])
        # Refresh provenance/eligibility even when System 1 is skipped.
        run_command("BUILD ARTICLE-LEVEL CLASSIFICATION QUEUE",[sys.executable,"build_classification_queue.py"])
        s1_summary=None
        if not args.skip_system1:
            print("\nSYSTEM 1 — JEV08")
            s1_summary=run_llm.main(limit=args.llm_limit)
        else:
            print("\nSystem 1 skipped; existing raw predictions are reused where still valid.")

        print("\nBUILD SYSTEM 2 ROUTING QUEUE")
        s2_queue_summary=build_system2_queue.build_queue()
        print(s2_queue_summary)
        s2_summary=None
        if not args.skip_system2:
            print("\nSYSTEM 2 — LFM2.5")
            s2_summary=run_system2.main(limit=args.system2_limit)
        else:
            print("System 2 execution skipped; routed articles remain pending.")

        print("\nCONSOLIDATION")
        consolidation_summary=consolidate(allow_pending_system2=True)
        print(consolidation_summary)

        if not args.skip_digest:
            digest_path=generate_digest(output_dir/"watchtower_digest.md")
            csv_path=export_classifications(output_dir/"watchtower_classifications.csv",include_needs_review=True)
            print(f"\nDigest: {digest_path}\nCSV: {csv_path}")
        else:
            print("\nDigest and CSV skipped.")
        if backup: print(f"Database backup: {backup}")
        print("\nWATCHTOWER PIPELINE COMPLETED")
        print(f"System 1 processed: {(s1_summary or {}).get('processed',0)}")
        print(f"System 2 processed: {(s2_summary or {}).get('processed',0)}")
        print(f"Consolidated: {consolidation_summary.get('consolidated',0)}")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Persisted work is retained; rerun to resume.")
        return 130
    except Exception as exc:
        print(f"\nPIPELINE FAILED: {type(exc).__name__}: {exc}")
        return 1

if __name__=="__main__":
    raise SystemExit(main())
