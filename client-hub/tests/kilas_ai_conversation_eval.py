"""Offline Kilas AI conversation curriculum checks; never called by production requests.

The TSV curriculum gives each case three turns and a target behavior. The optional
candidate evaluator is deliberately isolated from CI's deterministic policy checks:
live model wording is reviewed separately rather than making every build flaky.
"""
import argparse
import csv
import json
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")


def _rows(filename):
    with (FIXTURES / filename).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def curriculum():
    return {row["id"]: row for row in _rows("kilas_ai_conversation_curriculum.tsv")}


def golden():
    return _rows("kilas_ai_golden_conversations.tsv")


def evaluate_candidate(case, reply):
    """Cheap red flags for a separately sampled model run, not a semantic judge."""
    reply = str(reply or "").strip()
    failures = []
    if not reply:
        failures.append("empty_response")
    lowered = reply.casefold()
    forbidden = case["avoid"].casefold()
    if forbidden and forbidden in lowered:
        failures.append("known_bad_pattern")
    if lowered.startswith(("tentu! berikut adalah", "baik! berikut adalah", "tentu, berikut adalah")):
        failures.append("canned_opening")
    return failures


def main():
    parser = argparse.ArgumentParser(description="Evaluate sampled Kilas AI Golden responses offline")
    parser.add_argument("responses_json", help="JSON object mapping Golden case IDs to candidate responses")
    args = parser.parse_args()
    responses = json.loads(Path(args.responses_json).read_text(encoding="utf-8"))
    cases = curriculum()
    report = {row["scenario_id"]: evaluate_candidate(cases[row["scenario_id"]],
              responses.get(row["scenario_id"], "")) for row in golden()}
    print(json.dumps({"checked": len(report), "failures": {key: value for key, value in report.items() if value}},
                     ensure_ascii=False, indent=2))
    raise SystemExit(1 if any(report.values()) else 0)


if __name__ == "__main__":
    main()
