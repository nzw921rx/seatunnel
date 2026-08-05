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

"""Render normalized SeaTunnel benchmark results as a Markdown report."""

import argparse
import json
import pathlib
import statistics


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, action="append", type=pathlib.Path)
    parser.add_argument("--baseline", action="append", default=[], type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    return parser.parse_args()


def format_number(value):
    if value is None:
        return "n/a"
    absolute = abs(value)
    if absolute >= 1000:
        return "{:,.2f}".format(value)
    if absolute >= 1:
        return "{:.3f}".format(value)
    return "{:.6f}".format(value)


def load_report(path):
    with path.open(encoding="utf-8") as handle:
        report = json.load(handle)
    if report.get("schema_version") != 1:
        raise ValueError("Unsupported benchmark report schema in {}".format(path))
    return report


def report_lines(report):
    environment = report["environment"]
    lines = [
        "## SeaTunnel benchmark report",
        "",
        "- Ref: `{}`".format(report["source"]["ref"]),
        "- Commit: `{}`".format(report["source"]["commit"]),
        "- Suite: `{}`".format(report["source"].get("suite") or "custom"),
        "- Java: `{}`".format(
            environment.get("jdk_version", environment["java_requested"])
        ),
        "- Environment: `{}`".format(environment["name"]),
        "- Runner image: `{}`".format(environment.get("runner_image", "unknown")),
        "- CPU: `{}`".format(environment.get("cpu_model", "unknown")),
        "",
        "> This report is observational. GitHub-hosted runner performance varies between hosts, "
        "so a single run is not a performance regression gate.",
        "",
        "| Metric | Value | Score error | Sample stddev | Unit | Better |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for metric in report["metrics"]:
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                metric["name"],
                format_number(metric["value"]),
                format_number(metric["score_error"]),
                format_number(metric["sample_standard_deviation"]),
                metric["unit"],
                metric["direction"],
            )
        )

    if report["pipeline_correctness"]:
        lines.extend(
            [
                "",
                "### Pipeline validity",
                "",
                "| Pipeline | Complete | Sustainable | Latency overflow rows |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for name, values in sorted(report["pipeline_correctness"].items()):
            lines.append(
                "| `{}` | {}/{} | {}/{} | {} |".format(
                    name,
                    values["complete_samples"],
                    values["sample_count"],
                    values["sustainable_samples"],
                    values["sample_count"],
                    values["latency_overflow_rows"],
                )
            )
    return lines


def metric_index(reports):
    indexed = {}
    for report in reports:
        for metric in report["metrics"]:
            indexed.setdefault(metric["name"], []).append(metric)
    return indexed


def median_value(metrics):
    values = [metric["value"] for metric in metrics if metric["value"] is not None]
    return statistics.median(values) if values else None


def format_percent(value):
    return "n/a" if value is None else "{:+.2f}%".format(value)


def source_summary(reports):
    refs = list(dict.fromkeys(report["source"]["ref"] for report in reports))
    commits = list(dict.fromkeys(report["source"]["commit"] for report in reports))
    return ", ".join(refs), ", ".join(commits)


def comparison_lines(baselines, candidates):
    baseline_metrics = metric_index(baselines)
    candidate_metrics = metric_index(candidates)
    baseline_ref, baseline_commit = source_summary(baselines)
    candidate_ref, candidate_commit = source_summary(candidates)
    environment = candidates[0]["environment"]
    suite = candidates[0]["source"].get("suite") or "custom"
    lines = [
        "## SeaTunnel benchmark comparison",
        "",
        "- Baseline: `{}` at `{}` ({} runs)".format(
            baseline_ref, baseline_commit, len(baselines)
        ),
        "- Candidate: `{}` at `{}` ({} runs)".format(
            candidate_ref, candidate_commit, len(candidates)
        ),
        "- Suite: `{}`".format(suite),
        "- Java: `{}`".format(
            environment.get("jdk_version", environment["java_requested"])
        ),
        "- Runner image: `{}`".format(environment.get("runner_image", "unknown")),
        "- CPU: `{}`".format(environment.get("cpu_model", "unknown")),
        "",
        "> Baseline and candidate ran alternately on the same worker. Positive adjusted change is "
        "favorable, but this observational report does not enforce a regression threshold.",
        "",
        "| Metric | Baseline median | Candidate median | Adjusted change | Unit | Better |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for name in sorted(set(baseline_metrics) | set(candidate_metrics)):
        baseline = median_value(baseline_metrics.get(name, []))
        candidate = median_value(candidate_metrics.get(name, []))
        metric = (candidate_metrics.get(name) or baseline_metrics[name])[0]
        raw_change = (
            (candidate / baseline - 1.0) * 100.0
            if baseline not in (None, 0.0) and candidate is not None
            else None
        )
        adjusted_change = (
            -raw_change if raw_change is not None and metric["direction"] == "lower" else raw_change
        )
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                name,
                format_number(baseline),
                format_number(candidate),
                format_percent(adjusted_change),
                metric["unit"],
                metric["direction"],
            )
        )
    return lines


def main():
    args = parse_args()
    reports = [load_report(path) for path in args.input]
    baselines = [load_report(path) for path in args.baseline]
    if baselines and not reports:
        raise ValueError("Candidate benchmark reports are required for comparison")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    lines = comparison_lines(baselines, reports) if baselines else report_lines(reports[0])
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
