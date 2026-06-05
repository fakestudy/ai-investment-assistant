#!/usr/bin/env python3
"""Collect current-project evidence for a daily technical review."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo


REPORT_PATTERN = re.compile(r"^(\d+)-(\d{4}-\d{2}-\d{2})\.md$")
MAX_UNTRACKED_FILE_BYTES = 50_000
MAX_UNTRACKED_TOTAL_BYTES = 200_000
SENSITIVE_FILENAMES = {
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
SENSITIVE_SUFFIXES = (".jks", ".key", ".keystore", ".p12", ".pem", ".pfx")
IGNORED_MESSAGE_PREFIXES = (
    "# AGENTS.md instructions for ",
    "<environment_context>",
    "<skill>",
)


def run_git(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def resolve_project_root(project_path: Path) -> Path:
    path = project_path.expanduser().resolve()
    output = run_git(path, "rev-parse", "--show-toplevel").strip()
    return Path(output).resolve()


def resolve_review_date(raw_date: Optional[str], timezone_name: str) -> date:
    if raw_date:
        return date.fromisoformat(raw_date)
    return datetime.now(ZoneInfo(timezone_name)).date()


def is_within_project(candidate: Path, project_root: Path) -> bool:
    try:
        candidate.expanduser().resolve().relative_to(project_root)
        return True
    except (OSError, ValueError):
        return False


def parse_timestamp(raw_timestamp: object) -> Optional[datetime]:
    if not isinstance(raw_timestamp, str) or not raw_timestamp:
        return None
    normalized = raw_timestamp[:-1] + "+00:00" if raw_timestamp.endswith("Z") else raw_timestamp
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def timestamp_is_on_date(
    raw_timestamp: object,
    review_date: date,
    timezone_name: str,
) -> bool:
    parsed = parse_timestamp(raw_timestamp)
    if parsed is None:
        return False
    return parsed.astimezone(ZoneInfo(timezone_name)).date() == review_date


def session_candidates(codex_home: Path, review_date: date) -> Iterable[Path]:
    paths = set()
    sessions_root = codex_home / "sessions"
    for offset in (-1, 0, 1):
        candidate_date = review_date + timedelta(days=offset)
        day_dir = sessions_root / candidate_date.strftime("%Y/%m/%d")
        if day_dir.exists():
            paths.update(day_dir.glob("*.jsonl"))

    archived_root = codex_home / "archived_sessions"
    if archived_root.exists():
        paths.update(archived_root.rglob("*.jsonl"))
    return sorted(paths)


def read_json_lines(path: Path) -> Iterable[Dict[str, object]]:
    try:
        with path.open(encoding="utf-8") as source:
            for line in source:
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def is_noise_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return any(stripped.startswith(prefix) for prefix in IGNORED_MESSAGE_PREFIXES)


def extract_message_text(payload: Dict[str, object]) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return "" if is_noise_text(content) else content.strip()
    if not isinstance(content, list):
        return ""

    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in {"input_text", "output_text", "text"}:
            continue
        text = item.get("text")
        if isinstance(text, str) and not is_noise_text(text):
            parts.append(text.strip())
    return "\n\n".join(parts)


def collect_conversations(
    project_root: Path,
    codex_home: Path,
    review_date: date,
    timezone_name: str,
) -> List[Dict[str, object]]:
    conversations = []
    for path in session_candidates(codex_home, review_date):
        session_id = path.stem
        current_cwd = None
        relevant_cwd = None
        messages = []

        for record in read_json_lines(path):
            record_type = record.get("type")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue

            if record_type == "session_meta":
                session_id = str(payload.get("id") or session_id)
                current_cwd = payload.get("cwd")
                continue
            if record_type == "turn_context":
                current_cwd = payload.get("cwd") or current_cwd
                continue
            if record_type != "response_item":
                continue
            if payload.get("type") != "message":
                continue
            if payload.get("role") not in {"user", "assistant"}:
                continue
            if not isinstance(current_cwd, str):
                continue
            if not is_within_project(Path(current_cwd), project_root):
                continue
            if not timestamp_is_on_date(record.get("timestamp"), review_date, timezone_name):
                continue

            text = extract_message_text(payload)
            if not text:
                continue
            relevant_cwd = relevant_cwd or str(Path(current_cwd).expanduser().resolve())
            messages.append(
                {
                    "role": payload["role"],
                    "text": text,
                    "timestamp": record.get("timestamp"),
                }
            )

        if messages:
            conversations.append(
                {
                    "session_id": session_id,
                    "source_file": str(path),
                    "cwd": relevant_cwd,
                    "messages": messages,
                }
            )
    return conversations


def collect_commits(
    project_root: Path,
    branch: str,
    review_date: date,
    timezone_name: str,
) -> List[Dict[str, str]]:
    head_check = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
    )
    if head_check.returncode != 0:
        return []

    timezone = ZoneInfo(timezone_name)
    day_start = datetime.combine(review_date, time.min, timezone)
    next_day_start = day_start + timedelta(days=1)
    ref = branch or "HEAD"
    raw_log = run_git(
        project_root,
        "log",
        ref,
        "--since=" + day_start.isoformat(),
        "--before=" + next_day_start.isoformat(),
        "--format=%H%x1f%aI%x1f%cI%x1f%s%x1e",
    )

    commits = []
    for entry in raw_log.split("\x1e"):
        entry = entry.strip()
        if not entry:
            continue
        fields = entry.split("\x1f", 3)
        if len(fields) != 4:
            continue
        sha, author_date, commit_date, subject = fields
        commits.append(
            {
                "sha": sha,
                "author_date": author_date,
                "commit_date": commit_date,
                "subject": subject,
                "diff": run_git(
                    project_root,
                    "show",
                    "--format=fuller",
                    "--stat",
                    "--patch",
                    "--no-ext-diff",
                    sha,
                ),
            }
        )
    return commits


def collect_git_evidence(
    project_root: Path,
    review_date: date,
    timezone_name: str,
) -> Dict[str, object]:
    branch = run_git(project_root, "branch", "--show-current").strip()
    status = run_git(project_root, "status", "--short")
    staged_diff = run_git(project_root, "diff", "--cached", "--no-ext-diff")
    unstaged_diff = run_git(project_root, "diff", "--no-ext-diff")
    untracked_files = collect_untracked_files(project_root)
    untracked_diff = "\n\n".join(
        (
            f"--- /dev/null\n+++ b/{item['path']}\n"
            f"@@ untracked file @@\n{item['content']}"
        )
        for item in untracked_files
    )
    working_tree_diff = "\n".join(
        part
        for part in (
            staged_diff.strip(),
            unstaged_diff.strip(),
            untracked_diff.strip(),
        )
        if part
    )
    return {
        "branch": branch or None,
        "status": status,
        "commits": collect_commits(
            project_root,
            branch,
            review_date,
            timezone_name,
        ),
        "staged_diff": staged_diff,
        "unstaged_diff": unstaged_diff,
        "untracked_files": untracked_files,
        "working_tree_diff": working_tree_diff,
    }


def collect_untracked_files(project_root: Path) -> List[Dict[str, object]]:
    raw_paths = run_git(
        project_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    collected = []
    total_bytes = 0
    for relative_path in (item for item in raw_paths.split("\0") if item):
        if relative_path == "daily-reviews" or relative_path.startswith("daily-reviews/"):
            continue
        if is_sensitive_path(relative_path):
            continue
        path = project_root / relative_path
        if (
            path.is_symlink()
            or not path.is_file()
            or total_bytes >= MAX_UNTRACKED_TOTAL_BYTES
        ):
            continue
        remaining = MAX_UNTRACKED_TOTAL_BYTES - total_bytes
        read_limit = min(MAX_UNTRACKED_FILE_BYTES, remaining)
        try:
            data = path.read_bytes()[: read_limit + 1]
        except OSError:
            continue
        if b"\0" in data:
            continue
        try:
            content = data[:read_limit].decode("utf-8")
        except UnicodeDecodeError:
            continue
        truncated = len(data) > read_limit
        total_bytes += min(len(data), read_limit)
        collected.append(
            {
                "path": relative_path,
                "content": content,
                "truncated": truncated,
            }
        )
    return collected


def is_sensitive_path(relative_path: str) -> bool:
    name = Path(relative_path).name.lower()
    if name == ".env":
        return True
    if name.startswith(".env.") and name not in {
        ".env.example",
        ".env.sample",
        ".env.template",
    }:
        return True
    return name in SENSITIVE_FILENAMES or name.endswith(SENSITIVE_SUFFIXES)


def collect_report_context(project_root: Path, review_date: date) -> Dict[str, object]:
    reviews_dir = project_root / "daily-reviews"
    reports = []
    if reviews_dir.exists():
        for path in reviews_dir.iterdir():
            match = REPORT_PATTERN.match(path.name)
            if not match or not path.is_file():
                continue
            try:
                report_date = date.fromisoformat(match.group(2))
            except ValueError:
                continue
            reports.append(
                {
                    "sequence": int(match.group(1)),
                    "date": report_date,
                    "path": path,
                }
            )

    current_reports = [item for item in reports if item["date"] == review_date]
    current = max(current_reports, key=lambda item: item["sequence"], default=None)
    if current is None:
        next_sequence = max(
            (item["sequence"] for item in reports),
            default=0,
        ) + 1
        current_path = reviews_dir / f"{next_sequence:02d}-{review_date.isoformat()}.md"
    else:
        next_sequence = current["sequence"]
        current_path = current["path"]

    previous_reports = [item for item in reports if item["date"] < review_date]
    previous = max(
        previous_reports,
        key=lambda item: (item["date"], item["sequence"]),
        default=None,
    )
    previous_path = previous["path"] if previous else None

    return {
        "current_path": str(current_path),
        "current_exists": current_path.exists(),
        "current_content": read_text(current_path),
        "sequence": next_sequence,
        "previous_path": str(previous_path) if previous_path else None,
        "previous_content": read_text(previous_path),
    }


def read_text(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def collect_context(
    project_path: Path,
    codex_home: Path,
    timezone_name: str = "Asia/Shanghai",
    raw_date: Optional[str] = None,
) -> Dict[str, object]:
    project_root = resolve_project_root(project_path)
    review_date = resolve_review_date(raw_date, timezone_name)
    conversations = collect_conversations(
        project_root,
        codex_home.expanduser().resolve(),
        review_date,
        timezone_name,
    )
    git_evidence = collect_git_evidence(project_root, review_date, timezone_name)
    report = collect_report_context(project_root, review_date)
    working_tree_changed = bool(git_evidence["status"].strip())
    evidence_counts = {
        "conversations": len(conversations),
        "commits": len(git_evidence["commits"]),
        "working_tree_changed": working_tree_changed,
    }

    return {
        "project": {
            "root": str(project_root),
            "branch": git_evidence["branch"],
        },
        "review": {
            "date": review_date.isoformat(),
            "timezone": timezone_name,
        },
        "conversations": conversations,
        "git": git_evidence,
        "report": report,
        "evidence_counts": evidence_counts,
        "has_reviewable_evidence": bool(
            conversations
            or git_evidence["commits"]
            or working_tree_changed
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect current-project evidence for a daily review.",
    )
    parser.add_argument("--project", default=".", help="Path inside the Git project.")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--date", help="Review date in YYYY-MM-DD format.")
    parser.add_argument(
        "--codex-home",
        default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = collect_context(
            project_path=Path(args.project),
            codex_home=Path(args.codex_home),
            timezone_name=args.timezone,
            raw_date=args.date,
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"daily-review context collection failed: {error}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
