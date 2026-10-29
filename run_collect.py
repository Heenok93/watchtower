"""RSS collection with per-feed validation and explicit status classification."""
from __future__ import annotations

import logging
import socket
import sqlite3
from urllib.error import URLError

from collectors.rss_collector import collect_rss_feed
from processing.deduplicate import build_article_fingerprint, get_duplicate_reason
from processing.normalize import normalize_doi
from storage.repositories import save_article, count_articles
from storage.run_repository import start_processing_run, finish_processing_run
from utils.config import load_yaml

LOG_DIR = "logs"


def configure_logging() -> None:
    import os
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(LOG_DIR, "collect_validation.log"), encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )


def classify_status(diagnostics: dict, found: int, errors: int) -> tuple[str, str]:
    """Return (status, explanation); zero-entry feeds are never silently successful."""
    http_status = diagnostics.get("http_status")
    bozo = diagnostics.get("bozo", False)
    exception = (diagnostics.get("fetch_error") or diagnostics.get("bozo_exception") or "").lower()
    without_title = diagnostics.get("entries_without_title", 0)

    network_markers = (
        "urlopen error", "timed out", "timeout", "getaddrinfo",
        "connection refused", "connection reset", "remote end closed",
        "ssl", "certificate verify failed", "temporary failure",
        "name resolution", "max retries exceeded", "connectionerror",
        "readtimeout", "connecttimeout", "requestexception",
    )
    network_failure = any(marker in exception for marker in network_markers)
    http_failure = isinstance(http_status, int) and http_status >= 400

    if http_failure or network_failure:
        return "failed", f"transport/HTTP failure (HTTP={http_status}; {exception or 'no details'})"
    if found == 0 and bozo:
        return "failed", f"invalid/unreadable feed with no usable entries ({exception or 'parser warning'})"
    if found == 0:
        return "partial", "feed parsed but returned zero usable entries; verify endpoint/content"
    if bozo or errors or without_title:
        reasons = []
        if bozo:
            reasons.append("parser warning")
        if errors:
            reasons.append(f"{errors} article-processing error(s)")
        if without_title:
            reasons.append(f"{without_title} entr(y/ies) without title")
        return "partial", "; ".join(reasons)
    return "success", "feed parsed and usable entries collected"


def main() -> None:
    configure_logging()
    log = logging.getLogger("watchtower.collect")
    sources = load_yaml("sources.yaml") or {}
    rss_sources = sources.get("rss", []) or []
    enabled_sources = [s for s in rss_sources if s.get("enabled", True)]

    totals = {"found": 0, "inserted": 0, "skipped": 0, "errors": 0}
    statuses = {"success": 0, "partial": 0, "failed": 0}
    source_results = []

    print("=" * 88)
    print("WATCHTOWER RSS COLLECTION — VALIDATION DES FLUX")
    print("=" * 88)
    print(f"Flux RSS activés : {len(enabled_sources)}")

    for source in enabled_sources:
        source_name = source.get("name") or source.get("id") or source.get("url") or "rss_unknown"
        source_id = source.get("id", source_name)
        source_url = source.get("url", "")
        content_type = source.get("content_type", "unknown")
        journal = source.get("journal")
        print("\n" + "-" * 88)
        print(f"Source : {source_name} [{source_id}]")
        print(f"URL : {source_url}")
        if journal:
            print(f"Journal : {journal}")

        run_id = start_processing_run(source=source_name)
        found = inserted = skipped = errors = 0
        duplicate_reasons = {"doi": 0, "pmid": 0, "source_url": 0, "fingerprint": 0}
        diagnostics: dict = {}

        try:
            articles = collect_rss_feed(
                url=source_url,
                source_name=source_name,
                content_type=content_type,
                journal=journal,
                diagnostics=diagnostics,
            )
            found = len(articles)
            for article in articles:
                try:
                    article.doi = normalize_doi(article.doi)
                    duplicate_reason = get_duplicate_reason(article)
                    if duplicate_reason:
                        skipped += 1
                        if duplicate_reason in duplicate_reasons:
                            duplicate_reasons[duplicate_reason] += 1
                        continue
                    fingerprint = build_article_fingerprint(article)
                    save_article(article=article, fingerprint=fingerprint)
                    inserted += 1
                except sqlite3.IntegrityError as exc:
                    # Concurrent inserts / unique constraint: treat as duplicate, not a source failure.
                    skipped += 1
                    log.info("Unique constraint while saving %s (%s): %s", source_name, article.title, exc)
                except Exception:
                    errors += 1
                    log.exception("Article processing failed: source=%s title=%r", source_name, article.title)
        except Exception:
            errors += 1
            diagnostics.setdefault("bozo_exception", "unhandled collection exception")
            log.exception("Feed collection crashed: source=%s url=%s", source_name, source_url)

        status, reason = classify_status(diagnostics, found, errors)
        statuses[status] += 1
        finish_processing_run(
            run_id=run_id,
            items_found=found,
            items_inserted=inserted,
            duplicate_reasons=duplicate_reasons,
            errors=errors,
            status=status,
        )

        totals["found"] += found
        totals["inserted"] += inserted
        totals["skipped"] += skipped
        totals["errors"] += errors
        result = {
            "source": source_name, "source_id": source_id, "url": source_url,
            "status": status, "reason": reason, "found": found,
            "inserted": inserted, "skipped": skipped, "errors": errors,
            "http_status": diagnostics.get("http_status"),
            "feed_title": diagnostics.get("feed_title"),
            "feed_version": diagnostics.get("feed_version"),
            "bozo": diagnostics.get("bozo", False),
            "bozo_exception": diagnostics.get("bozo_exception"),
            "fetch_error_type": diagnostics.get("fetch_error_type"),
            "fetch_error": diagnostics.get("fetch_error"),
            "entries_received": diagnostics.get("entries_received", 0),
            "entries_without_title": diagnostics.get("entries_without_title", 0),
            "encoding_retry_used": diagnostics.get("encoding_retry_used", False),
            "response_url": diagnostics.get("response_url", source_url),
            "response_content_type": diagnostics.get("response_content_type"),
            "response_bytes": diagnostics.get("response_bytes"),
            "encoding_retry_error": diagnostics.get("encoding_retry_error"),
            "run_id": run_id,
        }
        source_results.append(result)

        print(f"Validation : {status.upper()} — {reason}")
        print(f"HTTP : {result['http_status']} | Format : {result['feed_version']} | Titre du flux : {result['feed_title'] or '(absent)'}")
        if result.get("encoding_retry_used"):
            print("Récupération encodage : succès (déclaration US-ASCII corrigée en UTF-8)")
        if result.get("response_content_type"):
            print(f"Réponse brute : {result['response_content_type']} | {result.get('response_bytes')} octets | URL finale : {result.get('response_url')}")
        print(f"Entrées reçues : {result['entries_received']} | Articles utilisables : {found} | Sans titre : {result['entries_without_title']}")
        print(f"Insérés : {inserted} | Doublons : {skipped} | Erreurs de traitement : {errors} | Run ID : {run_id}")
        if diagnostics.get("bozo_exception"):
            print(f"Détail validation : {diagnostics['bozo_exception']}")
        log.info(
            "FEED_RESULT source=%s status=%s found=%d inserted=%d skipped=%d errors=%d http=%s version=%s bozo=%s reason=%s url=%s",
            source_name, status, found, inserted, skipped, errors,
            result["http_status"], result["feed_version"], result["bozo"], reason, source_url,
        )

    print("\n" + "=" * 88)
    print("BILAN DE COLLECTE")
    print("=" * 88)
    print(f"Flux : {len(enabled_sources)} | SUCCESS : {statuses['success']} | PARTIAL : {statuses['partial']} | FAILED : {statuses['failed']}")
    print(f"Articles trouvés : {totals['found']}")
    print(f"Articles insérés : {totals['inserted']}")
    print(f"Doublons ignorés : {totals['skipped']}")
    print(f"Erreurs de traitement : {totals['errors']}")
    print(f"Articles en base : {count_articles()}")
    print("\nFlux à vérifier :")
    flagged = [r for r in source_results if r["status"] != "success"]
    if not flagged:
        print("Aucun flux partiel ou en échec.")
    for r in flagged:
        print(f"- [{r['status'].upper()}] {r['source']} : {r['reason']} — {r['url']}")
    print("\nJournal détaillé : logs/collect_validation.log")
    print("Rapport machine-readable : logs/feed_validation_report.csv")

    # CSV report makes it easy to sort/filter failing sources in a spreadsheet.
    import csv
    import os
    os.makedirs(LOG_DIR, exist_ok=True)
    report_path = os.path.join(LOG_DIR, "feed_validation_report.csv")
    fields = list(source_results[0].keys()) if source_results else []
    if fields:
        with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(source_results)


if __name__ == "__main__":
    main()
