"""Store a validated history snapshot read directly from Tsenta MCP.

This is a milestone-one baseline, not a poller or manual application-entry API.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def normalize_status(status):
    return {
        "COMPLETED": "confirmed_submitted",
        "FAILED": "failed",
        "SKIPPED": "skipped",
        "READY": "processing",
        "RUNNING": "processing",
        "OPTIMIZING_RESUME": "processing",
        "OPTIMIZING_CL": "processing",
        "PENDING_RESUME_REVIEW": "needs_action",
        "PENDING_CL_REVIEW": "needs_action",
        "PENDING_SUBMIT_REVIEW": "needs_action",
    }.get(status, "unknown")


def unpack_page(capture):
    if capture.get("tool") != "list-applications":
        raise ValueError("Expected application history read")
    arguments = capture.get("arguments", {})
    if arguments.get("filter", "all") != "all" or "query" in arguments:
        raise ValueError("A filtered snapshot cannot form the full baseline")
    response = capture["response"]
    if "error" in response or response.get("result", {}).get("isError"):
        raise ValueError("Failed source read")
    envelope = response["result"]["structuredContent"]
    if envelope.get("tool") != "list-applications":
        raise ValueError("Unexpected response tool")
    result = envelope["result"]
    pagination = result["pagination"]
    if pagination["page"] != arguments.get("page", 1) or pagination["limit"] != arguments.get("limit", 25):
        raise ValueError("Source pagination does not match requested page")
    return result


def validate_snapshot(captures):
    pages = [unpack_page(capture) for capture in captures]
    if not pages:
        raise ValueError("Missing history")
    pagination = pages[0]["pagination"]
    total, limit, total_pages = (pagination[key] for key in ("total", "limit", "totalPages"))
    if any(type(v) is not int for v in (total, limit, total_pages)) or total < 0 or not 1 <= limit <= 100:
        raise ValueError("Invalid history counts")
    expected_pages = max(1, (total + limit - 1) // limit)
    if total_pages != expected_pages or len(pages) != expected_pages:
        raise ValueError("History is incomplete")
    rows = []
    for number, page in enumerate(pages, 1):
        if page["pagination"] != {"page": number, "limit": limit, "total": total, "totalPages": total_pages}:
            raise ValueError("History shifted or a page is missing")
        items = page["applications"]
        if len(items) != min(limit, total - (number - 1) * limit):
            raise ValueError("Unexpected history page length")
        rows.extend(items)
    identifiers = [row.get("applicationId") for row in rows]
    if any(not isinstance(value, str) or not value for value in identifiers) or len(set(identifiers)) != total:
        raise ValueError("Missing or repeated stable source IDs")
    for row in rows:
        if not isinstance(row.get("status"), str):
            raise ValueError("Missing source status")
    counts = pages[0].get("counts", {})
    if counts and (counts.get("all") != total or counts.get("submitted") != sum(r["status"] == "COMPLETED" for r in rows)):
        raise ValueError("History and source counts disagree")
    return rows


def save_baseline(captures, database):
    rows = validate_snapshot(captures)
    fingerprint = hashlib.sha256(json.dumps(sorted(rows, key=lambda r: r["applicationId"]), sort_keys=True).encode()).hexdigest()
    database = Path(database)
    database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(database), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)
    connection = sqlite3.connect(str(database))
    try:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS baseline (singleton INTEGER PRIMARY KEY CHECK(singleton=1), fingerprint TEXT NOT NULL, imported_at TEXT NOT NULL, record_count INTEGER NOT NULL, automation_state TEXT NOT NULL)")
            connection.execute("""CREATE TABLE IF NOT EXISTS applications (
                source_application_id TEXT PRIMARY KEY, company TEXT, role TEXT,
                job_url TEXT, job_description TEXT, submitted_at TEXT,
                submitted_resume_reference TEXT, source_resume_profile_id TEXT,
                source_status TEXT NOT NULL, normalized_status TEXT NOT NULL,
                source_created_at TEXT, source_updated_at TEXT,
                historical INTEGER NOT NULL CHECK(historical=1),
                confirmed_at_baseline INTEGER NOT NULL,
                missing_fields TEXT NOT NULL, research_state TEXT NOT NULL
            )""")
            previous = connection.execute("SELECT fingerprint FROM baseline WHERE singleton=1").fetchone()
            if previous:
                if previous[0] != fingerprint:
                    raise ValueError("Baseline already exists; cannot replace it with a different snapshot")
                return len(rows)
            for row in rows:
                fields = {"company": row.get("companyName"), "role": row.get("jobTitle"), "job_url": row.get("url"),
                          "job_description": None, "submitted_at": None, "submitted_resume_reference": None}
                missing = [key for key, value in fields.items() if value is None or value == ""]
                connection.execute("INSERT INTO applications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    row["applicationId"], fields["company"], fields["role"], fields["job_url"], None, None, None,
                    row.get("resumeProfileId"), row["status"], normalize_status(row["status"]),
                    row.get("createdAt"), row.get("updatedAt"), 1, int(row["status"] == "COMPLETED"),
                    json.dumps(missing), "historical_no_outreach",
                ))
            connection.execute("INSERT INTO baseline VALUES (1,?,?,?,?)", (
                fingerprint, datetime.now(timezone.utc).isoformat(), len(rows),
                "blocked_unverified_mcp_polling_limits",
            ))
        return len(rows)
    finally:
        connection.close()
