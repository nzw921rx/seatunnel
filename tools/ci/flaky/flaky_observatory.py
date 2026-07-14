#!/usr/bin/env python3
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Collect and classify SeaTunnel CI flaky-test observations.

The script intentionally uses only the Python standard library so it can run on
GitHub hosted runners before project dependencies are available.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
DEFAULT_ISSUE_TITLE = "[CI][Flaky] 30-day dev branch and PR CI observatory"
ROOT_CAUSE_TYPES = {
    "ci_architecture",
    "pr_e2e_quality",
    "flaky_test",
    "testcontainers_engine_base",
    "product_code_regression",
}
FAILED_CHECK_CONCLUSIONS = {
    "failure",
    "timed_out",
    "cancelled",
    "action_required",
    "startup_failure",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: Dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def read_text(path: Optional[str]) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8", errors="replace")


def normalize_text(value: Optional[str], limit: int = 240) -> str:
    if not value:
        return ""
    text = " ".join(value.split())
    replacements = [
        (r"0x[0-9a-fA-F]+", "<hex>"),
        (r"\b[0-9a-f]{7,40}\b", "<sha>"),
        (r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-Z]*\b", "<timestamp>"),
        (r"\b\d+\b", "<num>"),
        (r"/(?:private/)?tmp/[^\s:]+", "<tmp>"),
        (r"/home/runner/work/[^\s:]+", "<workspace>"),
        (r"/Users/[^/\s]+/[^\s:]+", "<userpath>"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text[:limit]


def first_interesting_line(text: str) -> str:
    patterns = (
        "Exception",
        "Error",
        "Failure",
        "failed",
        "FAILED",
        "Timed out",
        "timeout",
        "No space left",
        "ContainerLaunchException",
        "Could not start",
    )
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(pattern in stripped for pattern in patterns):
            return stripped[:500]
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped[:500]
    return ""


def detect_exception_type(text: str, fallback: str = "UnknownFailure") -> str:
    if not text:
        return fallback
    patterns = [
        r"([A-Za-z0-9_.$]+Exception)",
        r"([A-Za-z0-9_.$]+Error)",
        r"(AssertionFailedError)",
        r"(BUILD FAILURE)",
        r"(Timed out)",
        r"(No space left on device)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace(" ", "")
    return fallback


def detect_phase(report_path: Optional[Path], text: str, exit_code: int) -> str:
    lower = text.lower()
    path_text = str(report_path or "")
    if "compilation failure" in lower or "mavencompilerplugin" in lower:
        return "compile"
    if "no space left" in lower or "runner" in lower and "lost communication" in lower:
        return "timeout" if "timeout" in lower or "timed out" in lower else "cleanup"
    if "timed out" in lower or "timeout" in lower:
        return "timeout"
    if "containerlaunchexception" in lower or "could not start container" in lower:
        return "container_start"
    if "testcontainers" in lower and ("startup" in lower or "container" in lower):
        return "container_start"
    if "failsafe-reports" in path_text:
        return "test_assertion"
    if "surefire-reports" in path_text:
        return "unit_test"
    if exit_code != 0:
        return "test_assertion"
    return "unit_test"


def detect_engine(*values: Optional[str]) -> str:
    text = " ".join(value or "" for value in values).lower()
    if "flink" in text:
        return "flink"
    if "spark" in text:
        return "spark"
    if "zeta" in text or "seatunnel" in text and "engine" in text:
        return "zeta"
    return "unknown"


def detect_container_id(text: str) -> str:
    patterns = [
        r"\b(FLINK_[0-9_]+)\b",
        r"\b(SPARK_[0-9_]+)\b",
        r"\b(SEATUNNEL|ZETA)\b",
        r"TestContainerId\.([A-Z0-9_]+)",
        r"container(?: id)?:?\s*([a-zA-Z0-9_.-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return "unknown"


def module_from_report_path(report_path: Path, workspace: Path) -> str:
    try:
        relative = report_path.resolve().relative_to(workspace.resolve())
    except ValueError:
        relative = report_path
    parts = list(relative.parts)
    if "target" not in parts:
        return "unknown"
    target_index = parts.index("target")
    if target_index == 0:
        return "unknown"
    return parts[target_index - 1]


def git_sha(workspace: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return os.environ.get("GITHUB_SHA", "")


def base_dev_pr_fingerprint(dev_sha: str) -> Dict[str, Any]:
    return {
        "source_type": "dev_schedule",
        "dev_sha": dev_sha,
        "pr_number": "",
        "head_sha": "",
        "base_sha": "",
        "author": "",
        "labels": [],
        "changed_modules": [],
        "changed_e2e_modules": [],
        "changed_test_files": [],
        "changed_test_file_count": 0,
        "changed_test_file_count_bucket": "0",
        "touched_connectors": [],
        "touched_engines": [],
        "touched_workflows": False,
        "touched_testcontainers_base": False,
        "production_diff_size": 0,
        "test_diff_size": 0,
        "e2e_diff_size": 0,
        "is_docs_only": False,
        "is_dependency_change": False,
        "is_ci_change": False,
    }


def pr_pattern_payload(pr_fingerprint: Dict[str, Any]) -> Dict[str, Any]:
    """Return the fields that describe a PR type rather than one PR instance."""
    keys = [
        "labels",
        "changed_modules",
        "changed_e2e_modules",
        "changed_test_file_count_bucket",
        "touched_connectors",
        "touched_engines",
        "touched_workflows",
        "touched_testcontainers_base",
        "production_diff_size_bucket",
        "test_diff_size_bucket",
        "e2e_diff_size_bucket",
        "is_docs_only",
        "is_dependency_change",
        "is_ci_change",
    ]
    return {key: pr_fingerprint.get(key) for key in keys}


def size_bucket(value: int) -> str:
    if value == 0:
        return "0"
    if value <= 50:
        return "1-50"
    if value <= 250:
        return "51-250"
    if value <= 1000:
        return "251-1000"
    return "1000+"


def build_failure_fingerprint(
    *,
    workflow: str,
    job: str,
    java: str,
    os_name: str,
    module: str,
    test_class: str,
    test_method: str,
    engine: str,
    container_id: str,
    exception_type: str,
    message: str,
    top_stack: str,
    phase: str,
) -> Dict[str, Any]:
    return {
        "workflow": workflow or "unknown",
        "job": job or "unknown",
        "java": java or "unknown",
        "os": os_name or "unknown",
        "module": module or "unknown",
        "test_class": test_class or "",
        "test_method": test_method or "",
        "engine": engine or "unknown",
        "container_id": container_id or "unknown",
        "exception_type": exception_type or "UnknownFailure",
        "normalized_message": normalize_text(message),
        "top_stack": normalize_text(top_stack, limit=320),
        "phase": phase or "test_assertion",
    }


def classify_root_cause(
    failure_fingerprint: Dict[str, Any], pr_fingerprint: Dict[str, Any], source_type: str
) -> str:
    phase = failure_fingerprint.get("phase", "")
    message = " ".join(
        [
            failure_fingerprint.get("normalized_message", ""),
            failure_fingerprint.get("top_stack", ""),
            failure_fingerprint.get("exception_type", ""),
            failure_fingerprint.get("job", ""),
        ]
    ).lower()
    module = failure_fingerprint.get("module", "")

    if phase == "compile":
        return "product_code_regression"
    if any(
        token in message
        for token in [
            "no space left",
            "runner",
            "dependency download",
            "could not resolve dependencies",
            "maven download",
            "artifact upload",
            "cache",
        ]
    ):
        return "ci_architecture"
    if phase in {"container_start", "cleanup"} or any(
        token in message
        for token in [
            "testcontainers",
            "containerlaunchexception",
            "could not start container",
            "waiting for container",
            "docker",
            "engine lifecycle",
        ]
    ):
        return "testcontainers_engine_base"
    if source_type == "pr_ci":
        changed_e2e = set(pr_fingerprint.get("changed_e2e_modules") or [])
        changed_tests = pr_fingerprint.get("changed_test_files") or []
        touched_base = pr_fingerprint.get("touched_testcontainers_base")
        if touched_base:
            return "testcontainers_engine_base"
        if changed_e2e or changed_tests:
            if not module or module == "unknown" or module in changed_e2e:
                return "pr_e2e_quality"
        if pr_fingerprint.get("production_diff_size", 0) > 0:
            return "product_code_regression"
    if phase == "timeout":
        return "ci_architecture"
    return "flaky_test"


def build_record(
    *,
    source_type: str,
    repository: str,
    dev_sha: str,
    run_url: str,
    failure_fingerprint: Dict[str, Any],
    pr_fingerprint: Dict[str, Any],
    details_url: str = "",
) -> Dict[str, Any]:
    if "production_diff_size_bucket" not in pr_fingerprint:
        pr_fingerprint = dict(pr_fingerprint)
        pr_fingerprint["production_diff_size_bucket"] = size_bucket(
            int(pr_fingerprint.get("production_diff_size") or 0)
        )
        pr_fingerprint["test_diff_size_bucket"] = size_bucket(
            int(pr_fingerprint.get("test_diff_size") or 0)
        )
        pr_fingerprint["e2e_diff_size_bucket"] = size_bucket(
            int(pr_fingerprint.get("e2e_diff_size") or 0)
        )
    root_cause_type = classify_root_cause(failure_fingerprint, pr_fingerprint, source_type)
    failure_id = stable_hash(failure_fingerprint)
    pr_id = stable_hash(pr_pattern_payload(pr_fingerprint))
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "source_type": source_type,
        "repository": repository,
        "dev_sha": dev_sha,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "run_url": run_url,
        "details_url": details_url,
        "failure_fingerprint_id": failure_id,
        "failure_fingerprint": failure_fingerprint,
        "pr_fingerprint_id": pr_id,
        "pr_fingerprint": pr_fingerprint,
        "root_cause_type": root_cause_type,
    }


def testcase_failures(report_path: Path) -> Iterable[Tuple[ET.Element, ET.Element]]:
    try:
        root = ET.parse(report_path).getroot()
    except ET.ParseError:
        return []
    result = []
    for testcase in root.iter("testcase"):
        failure = testcase.find("failure")
        error = testcase.find("error")
        if failure is not None:
            result.append((testcase, failure))
        if error is not None:
            result.append((testcase, error))
    return result


def collect_reports(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    dev_sha = args.dev_sha or git_sha(workspace)
    log_text = read_text(args.log_file)
    pr_fingerprint = base_dev_pr_fingerprint(dev_sha)

    records: List[Dict[str, Any]] = []
    reports = sorted(workspace.rglob("target/surefire-reports/TEST-*.xml"))
    reports.extend(sorted(workspace.rglob("target/failsafe-reports/TEST-*.xml")))
    for report_path in reports:
        for testcase, failure in testcase_failures(report_path):
            failure_text = "\n".join(
                part for part in [failure.attrib.get("message", ""), failure.text or ""] if part
            )
            module = args.module or module_from_report_path(report_path, workspace)
            top_stack = first_interesting_line(failure_text)
            exception_type = failure.attrib.get("type") or detect_exception_type(failure_text)
            phase = detect_phase(report_path, failure_text, args.exit_code)
            engine = detect_engine(args.engine, args.job, module, failure_text)
            container_id = detect_container_id(failure_text)
            fingerprint = build_failure_fingerprint(
                workflow=args.workflow,
                job=args.job,
                java=args.java,
                os_name=args.os,
                module=module,
                test_class=testcase.attrib.get("classname", ""),
                test_method=testcase.attrib.get("name", ""),
                engine=engine,
                container_id=container_id,
                exception_type=exception_type,
                message=failure.attrib.get("message", "") or top_stack,
                top_stack=top_stack,
                phase=phase,
            )
            records.append(
                build_record(
                    source_type=args.source_type,
                    repository=args.repository,
                    dev_sha=dev_sha,
                    run_url=args.run_url,
                    failure_fingerprint=fingerprint,
                    pr_fingerprint=pr_fingerprint,
                )
            )

    if args.exit_code != 0 and not records:
        top_stack = first_interesting_line(log_text)
        exception_type = detect_exception_type(log_text)
        phase = detect_phase(None, log_text, args.exit_code)
        module = args.module or module_from_log(args.job, log_text)
        fingerprint = build_failure_fingerprint(
            workflow=args.workflow,
            job=args.job,
            java=args.java,
            os_name=args.os,
            module=module,
            test_class="",
            test_method="",
            engine=detect_engine(args.engine, args.job, module, log_text),
            container_id=detect_container_id(log_text),
            exception_type=exception_type,
            message=top_stack,
            top_stack=top_stack,
            phase=phase,
        )
        records.append(
            build_record(
                source_type=args.source_type,
                repository=args.repository,
                dev_sha=dev_sha,
                run_url=args.run_url,
                failure_fingerprint=fingerprint,
                pr_fingerprint=pr_fingerprint,
            )
        )

    with output.open("w", encoding="utf-8") as writer:
        for record in records:
            writer.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")
    print(f"Wrote {len(records)} observation(s) to {output}")
    return 0


def module_from_log(job: str, text: str) -> str:
    patterns = [
        r"-pl\s+(:?[A-Za-z0-9_.-]+)",
        r"Building\s+([A-Za-z0-9_.-]+)",
        r"\[INFO\]\s+Building\s+([A-Za-z0-9_.-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).lstrip(":")
    normalized_job = job.lower().replace(" ", "-")
    if "connector" in normalized_job or "engine" in normalized_job or "transform" in normalized_job:
        return normalized_job
    return "unknown"


class GitHubApi:
    def __init__(self, token: str):
        self.token = token

    def request(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        allow_unauth_retry: bool = True,
    ) -> Tuple[Any, Dict[str, str]]:
        data = None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "seatunnel-flaky-observatory",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
                return (json.loads(body) if body else None), dict(response.headers)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            if self.token and allow_unauth_retry and error.code in {403, 404}:
                original_token = self.token
                self.token = ""
                try:
                    return self.request(method, url, payload, allow_unauth_retry=False)
                finally:
                    self.token = original_token
            raise RuntimeError(f"GitHub API {method} {url} failed: {error.code} {body}") from error

    def get_json(self, url: str) -> Any:
        return self.request("GET", url)[0]

    def post_json(self, url: str, payload: Dict[str, Any]) -> Any:
        return self.request("POST", url, payload)[0]

    def patch_json(self, url: str, payload: Dict[str, Any]) -> Any:
        return self.request("PATCH", url, payload)[0]

    def paged(self, url: str) -> Iterable[Any]:
        while url:
            data, headers = self.request("GET", url)
            if isinstance(data, list):
                yield from data
            else:
                yield data
            url = next_link(headers.get("Link", ""))


def next_link(link_header: str) -> str:
    for chunk in link_header.split(","):
        section = chunk.strip()
        if 'rel="next"' in section:
            match = re.match(r"<([^>]+)>", section)
            if match:
                return match.group(1)
    return ""


def api_url(repository: str, path: str) -> str:
    return f"https://api.github.com/repos/{repository}/{path.lstrip('/')}"


def list_recent_prs(api: GitHubApi, repository: str, lookback_days: int, limit: int) -> List[int]:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)).date().isoformat()
    query = f"repo:{repository} is:pr is:open updated:>={since}"
    url = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
        {"q": query, "sort": "updated", "order": "desc", "per_page": min(limit, 100)}
    )
    data = api.get_json(url)
    return [int(item["number"]) for item in data.get("items", [])[:limit]]


def build_pr_fingerprint(
    pr_number: int, pull: Dict[str, Any], issue: Dict[str, Any], files: List[Dict[str, Any]]
) -> Dict[str, Any]:
    filenames = [file_info["filename"] for file_info in files]
    labels = sorted(label["name"] for label in issue.get("labels", []))
    changed_modules = sorted({module_name(path) for path in filenames if module_name(path)})
    changed_e2e_modules = sorted({e2e_module_name(path) for path in filenames if e2e_module_name(path)})
    changed_test_files = sorted(
        path
        for path in filenames
        if "/src/test/" in path or path.endswith("IT.java") or path.endswith("Test.java")
    )
    touched_connectors = sorted({connector_name(path) for path in filenames if connector_name(path)})
    touched_engines = sorted({engine_name(path) for path in filenames if engine_name(path)})
    touched_workflows = any(path.startswith(".github/workflows/") for path in filenames)
    touched_testcontainers_base = any(
        path.startswith("seatunnel-e2e/seatunnel-e2e-common/")
        or "TestSuiteBase.java" in path
        or "TestContainer" in path
        or "ContainerUtil.java" in path
        for path in filenames
    )
    production_diff_size = 0
    test_diff_size = 0
    e2e_diff_size = 0
    for file_info in files:
        changes = int(file_info.get("changes") or 0)
        filename = file_info["filename"]
        if "src/test/" in filename or filename.endswith("IT.java") or filename.endswith("Test.java"):
            test_diff_size += changes
        elif filename.startswith("seatunnel-e2e/"):
            e2e_diff_size += changes
        elif not filename.startswith("docs/") and not filename.endswith(".md"):
            production_diff_size += changes
    is_docs_only = bool(filenames) and all(path.startswith("docs/") or path.endswith(".md") for path in filenames)
    is_dependency_change = any(
        path.endswith("pom.xml")
        or "known-dependencies" in path
        or path.endswith("dependency-reduced-pom.xml")
        for path in filenames
    )
    is_ci_change = any(
        path.startswith(".github/")
        or path.startswith("tools/github/")
        or path.startswith("tools/update_modules_check/")
        for path in filenames
    )
    fingerprint = {
        "source_type": "pr_ci",
        "dev_sha": "",
        "pr_number": pr_number,
        "head_sha": pull.get("head", {}).get("sha", ""),
        "base_sha": pull.get("base", {}).get("sha", ""),
        "author": pull.get("user", {}).get("login", ""),
        "labels": labels,
        "changed_modules": changed_modules,
        "changed_e2e_modules": changed_e2e_modules,
        "changed_test_files": changed_test_files,
        "changed_test_file_count": len(changed_test_files),
        "changed_test_file_count_bucket": size_bucket(len(changed_test_files)),
        "touched_connectors": touched_connectors,
        "touched_engines": touched_engines,
        "touched_workflows": touched_workflows,
        "touched_testcontainers_base": touched_testcontainers_base,
        "production_diff_size": production_diff_size,
        "test_diff_size": test_diff_size,
        "e2e_diff_size": e2e_diff_size,
        "production_diff_size_bucket": size_bucket(production_diff_size),
        "test_diff_size_bucket": size_bucket(test_diff_size),
        "e2e_diff_size_bucket": size_bucket(e2e_diff_size),
        "is_docs_only": is_docs_only,
        "is_dependency_change": is_dependency_change,
        "is_ci_change": is_ci_change,
    }
    return fingerprint


def module_name(path: str) -> str:
    parts = path.split("/")
    if not parts:
        return ""
    if parts[0] == "seatunnel-connectors-v2" and len(parts) > 1:
        return parts[1]
    if parts[0] == "seatunnel-e2e" and len(parts) > 2:
        return parts[2]
    return parts[0]


def e2e_module_name(path: str) -> str:
    parts = path.split("/")
    candidates = []
    for part in parts:
        if part != "seatunnel-e2e" and part.endswith("-e2e"):
            candidates.append(part)
    if candidates:
        return candidates[-1]
    if parts and parts[0] == "seatunnel-e2e":
        return parts[0]
    return ""


def connector_name(path: str) -> str:
    for part in path.split("/"):
        if part.startswith("connector-"):
            return part
    return ""


def engine_name(path: str) -> str:
    lower = path.lower()
    if "flink" in lower:
        return "flink"
    if "spark" in lower:
        return "spark"
    if "seatunnel-engine" in lower or "zeta" in lower:
        return "zeta"
    return ""


def infer_module_from_check(name: str) -> str:
    lower = name.lower()
    for token in re.split(r"[^a-z0-9_.-]+", lower):
        if token.startswith("connector-") or token.startswith("seatunnel-"):
            return token
    return module_from_log(name, name)


def ingest_pr(args: argparse.Namespace) -> int:
    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    api = GitHubApi(token)
    pr_numbers = [int(args.pr_number)] if args.pr_number else list_recent_prs(
        api, args.source_repository, args.lookback_days, args.max_prs
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    records: List[Dict[str, Any]] = []
    for pr_number in pr_numbers:
        pull = api.get_json(api_url(args.source_repository, f"pulls/{pr_number}"))
        issue = api.get_json(api_url(args.source_repository, f"issues/{pr_number}"))
        files = list(api.paged(api_url(args.source_repository, f"pulls/{pr_number}/files?per_page=100")))
        pr_fingerprint = build_pr_fingerprint(pr_number, pull, issue, files)
        head_sha = pr_fingerprint.get("head_sha", "")
        if not head_sha:
            continue
        checks_url = api_url(
            args.source_repository,
            f"commits/{head_sha}/check-runs?per_page=100",
        )
        checks = api.get_json(checks_url).get("check_runs", [])
        for check_run in checks:
            conclusion = check_run.get("conclusion") or ""
            status = check_run.get("status") or ""
            if conclusion not in FAILED_CHECK_CONCLUSIONS:
                continue
            name = check_run.get("name") or "unknown"
            details_url = check_run.get("details_url") or check_run.get("html_url") or ""
            phase = "timeout" if conclusion == "timed_out" else "test_assertion"
            module = infer_module_from_check(name)
            message = f"{status}:{conclusion}:{name}"
            fingerprint = build_failure_fingerprint(
                workflow=check_run.get("app", {}).get("slug", "github-actions"),
                job=name,
                java="unknown",
                os_name="unknown",
                module=module,
                test_class="",
                test_method="",
                engine=detect_engine(name, module),
                container_id="unknown",
                exception_type=conclusion or status or "failed_check",
                message=message,
                top_stack=details_url,
                phase=phase,
            )
            records.append(
                build_record(
                    source_type="pr_ci",
                    repository=args.source_repository,
                    dev_sha="",
                    run_url=args.run_url,
                    details_url=details_url,
                    failure_fingerprint=fingerprint,
                    pr_fingerprint=pr_fingerprint,
                )
            )
    with output.open("w", encoding="utf-8") as writer:
        for record in records:
            writer.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")
    print(f"Wrote {len(records)} PR CI observation(s) to {output}")
    return 0


def load_records(paths: Sequence[Path], records_dir: Optional[Path]) -> List[Dict[str, Any]]:
    files: List[Path] = []
    files.extend(paths)
    if records_dir and records_dir.exists():
        files.extend(sorted(records_dir.rglob("*.jsonl")))
    records = []
    for file_path in files:
        if not file_path.exists():
            continue
        for line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
    return records


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]], limit: int = 10) -> str:
    if not rows:
        return "_No entries._"
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows[:limit]:
        output.append("| " + " | ".join(escape_markdown_cell(str(item)) for item in row) + " |")
    return "\n".join(output)


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def evidence_link(record: Dict[str, Any]) -> str:
    url = record.get("details_url") or record.get("run_url") or ""
    if not url:
        return ""
    return f"[run]({url})"


def summarize_records(records: List[Dict[str, Any]], mode: str, run_url: str) -> str:
    root_counts = Counter(record.get("root_cause_type", "unknown") for record in records)
    failure_counts = Counter(record.get("failure_fingerprint_id", "") for record in records)
    pr_counts = Counter(record.get("pr_fingerprint_id", "") for record in records)
    combo_counts = Counter(
        (record.get("failure_fingerprint_id", ""), record.get("pr_fingerprint_id", ""))
        for record in records
    )
    by_failure = {record.get("failure_fingerprint_id", ""): record for record in records}
    by_pr = {record.get("pr_fingerprint_id", ""): record for record in records}

    failure_rows = []
    for fingerprint_id, count in failure_counts.most_common(10):
        record = by_failure.get(fingerprint_id, {})
        fp = record.get("failure_fingerprint", {})
        failure_rows.append(
            [
                fingerprint_id,
                count,
                fp.get("job", ""),
                fp.get("module", ""),
                fp.get("phase", ""),
                record.get("root_cause_type", ""),
                evidence_link(record),
            ]
        )

    pr_rows = []
    for fingerprint_id, count in pr_counts.most_common(10):
        record = by_pr.get(fingerprint_id, {})
        fp = record.get("pr_fingerprint", {})
        pr_rows.append(
            [
                fingerprint_id,
                count,
                ",".join(fp.get("touched_connectors") or [])[:80],
                ",".join(fp.get("touched_engines") or [])[:80],
                fp.get("test_diff_size_bucket", ""),
                fp.get("production_diff_size_bucket", ""),
            ]
        )

    combo_rows = []
    for (failure_id, pr_id), count in combo_counts.most_common(10):
        record = by_failure.get(failure_id, {})
        combo_rows.append([failure_id, pr_id, count, evidence_link(record)])

    lines = [
        f"## {mode.title()} CI observatory update",
        "",
        f"- Generated at: `{utc_now()}`",
        f"- Source run: {run_url or '_not provided_'}",
        f"- Observation count: `{len(records)}`",
        "",
        "### Root cause counts",
        "",
        markdown_table(["root_cause_type", "count"], root_counts.most_common()),
        "",
        "### Top failure fingerprints",
        "",
        markdown_table(
            [
                "failure_fingerprint_id",
                "count",
                "job",
                "module",
                "phase",
                "root_cause_type",
                "evidence",
            ],
            failure_rows,
        ),
        "",
        "### Top PR fingerprints",
        "",
        markdown_table(
            [
                "pr_fingerprint_id",
                "count",
                "connectors",
                "engines",
                "test_size",
                "prod_size",
            ],
            pr_rows,
        ),
        "",
        "### Top failure + PR pairs",
        "",
        markdown_table(["failure_fingerprint_id", "pr_fingerprint_id", "count", "evidence"], combo_rows),
    ]
    if not records:
        lines.append("")
        lines.append("_No failed test observations were found in this run._")
    return "\n".join(lines)


def find_or_create_issue(api: GitHubApi, repository: str, title: str, dry_run: bool) -> int:
    if dry_run:
        return 0
    for issue in api.paged(api_url(repository, "issues?state=open&per_page=100")):
        if issue.get("pull_request"):
            continue
        if issue.get("title") == title:
            return int(issue["number"])
    body = textwrap.dedent(
        """\
        This issue is maintained by fork-only flaky observatory workflows.

        It tracks recurring CI failures using two independent fingerprints:
        `failure_fingerprint_id` for how a run failed, and `pr_fingerprint_id`
        for the PR shape that tends to trigger the failure.
        """
    )
    created = api.post_json(api_url(repository, "issues"), {"title": title, "body": body})
    return int(created["number"])


def update_issue(args: argparse.Namespace) -> int:
    records = load_records([Path(path) for path in args.records], Path(args.records_dir) if args.records_dir else None)
    body = summarize_records(records, args.mode, args.run_url)
    if args.dry_run:
        print(body)
        return 0
    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required unless --dry-run is used")
    api = GitHubApi(token)
    issue_number = find_or_create_issue(api, args.repository, args.title, False)
    api.post_json(api_url(args.repository, f"issues/{issue_number}/comments"), {"body": body})
    print(f"Updated issue #{issue_number}: {args.title}")
    return 0


def should_run_shard(args: argparse.Namespace) -> int:
    profile = args.profile
    shard = int(args.shard)
    weekday = dt.datetime.now(dt.timezone.utc).isoweekday()
    run = False
    if profile in {"weekly-full", "all"}:
        run = True
    elif profile == "connector-front":
        run = shard in {0, 1, 2, 3}
    elif profile == "connector-back":
        run = shard in {4, 5, 6, 7}
    elif profile == "daily":
        if weekday in {1, 3, 5}:
            run = shard in {0, 1, 2, 3}
        elif weekday in {2, 4, 6}:
            run = shard in {4, 5, 6, 7}
    print("run" if run else "skip")
    return 0 if run else 1


def should_run_special(args: argparse.Namespace) -> int:
    profile = args.profile
    weekday = dt.datetime.now(dt.timezone.utc).isoweekday()
    run = profile in {"weekly-full", "all", "high-risk"} or (
        profile == "daily" and weekday in {2, 4, 6}
    )
    print("run" if run else "skip")
    return 0 if run else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="Collect failed test observations")
    collect.add_argument("--workspace", required=True)
    collect.add_argument("--output", required=True)
    collect.add_argument("--exit-code", type=int, required=True)
    collect.add_argument("--log-file")
    collect.add_argument("--source-type", default="dev_schedule")
    collect.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    collect.add_argument("--workflow", default=os.environ.get("GITHUB_WORKFLOW", ""))
    collect.add_argument("--job", default=os.environ.get("GITHUB_JOB", ""))
    collect.add_argument("--java", default="")
    collect.add_argument("--os", default=os.environ.get("RUNNER_OS", ""))
    collect.add_argument("--module", default="")
    collect.add_argument("--engine", default="")
    collect.add_argument("--dev-sha", default="")
    collect.add_argument("--run-url", default="")
    collect.set_defaults(func=collect_reports)

    ingest = subparsers.add_parser("ingest-pr", help="Ingest failed checks for Apache PRs")
    ingest.add_argument("--source-repository", default="apache/seatunnel")
    ingest.add_argument("--pr-number", default="")
    ingest.add_argument("--lookback-days", type=int, default=2)
    ingest.add_argument("--max-prs", type=int, default=20)
    ingest.add_argument("--output", required=True)
    ingest.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    ingest.add_argument("--run-url", default="")
    ingest.set_defaults(func=ingest_pr)

    update = subparsers.add_parser("update-issue", help="Create or update the tracking issue")
    update.add_argument("--records", action="append", default=[])
    update.add_argument("--records-dir", default="")
    update.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    update.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    update.add_argument("--title", default=DEFAULT_ISSUE_TITLE)
    update.add_argument("--mode", default="daily")
    update.add_argument("--run-url", default="")
    update.add_argument("--dry-run", action="store_true")
    update.set_defaults(func=update_issue)

    shard = subparsers.add_parser("should-run-shard", help="Return whether a connector shard should run")
    shard.add_argument("--profile", required=True)
    shard.add_argument("--shard", required=True)
    shard.set_defaults(func=should_run_shard)

    special = subparsers.add_parser("should-run-special", help="Return whether high-risk jobs should run")
    special.add_argument("--profile", required=True)
    special.add_argument("--name", required=True)
    special.set_defaults(func=should_run_special)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
