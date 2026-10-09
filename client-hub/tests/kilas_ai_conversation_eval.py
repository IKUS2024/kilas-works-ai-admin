"""Offline Kilas AI conversation curriculum checks; never called by production requests.

The TSV curriculum gives each case three turns and a target behavior. The optional
candidate evaluator is deliberately isolated from CI's deterministic policy checks:
live model wording is reviewed separately rather than making every build flaky.
"""
import argparse
import csv
import json
import re
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


def professional_pairs():
    """Curated synthetic answers for offline review, never runtime prompt injection."""
    return json.loads((FIXTURES/'kilas_ai_professional_pairs.json').read_text(encoding='utf-8'))


def evaluate_professional(case, reply):
    """Fixture-specific missing-part/source red flags, not semantic truth scoring.

    Alternative correct wording needs human review; no word-count quality claim.
    """
    reply=str(reply or '').strip()
    if not reply:return ['empty_response']
    lowered=reply.casefold()
    failures=[]
    for name, alternatives in case.get('required_parts',{}).items():
        if not any(value.casefold() in lowered for value in alternatives):
            failures.append('missing_part:'+name)
    for value in case.get('forbidden',[]):
        if value.casefold() in lowered:failures.append('known_bad_pattern:'+value)
    if lowered.startswith(('tentu! berikut adalah','baik! berikut adalah','sebagai ai')):
        failures.append('canned_opening')
    for url in re.findall(r'https?://[^\s)\]>]+',reply,flags=re.I):
        if url.rstrip('.,;') not in case.get('allowed_urls',[]):
            failures.append('unreturned_url')
    if reply.count('?')>case.get('max_questions',1):failures.append('unnecessary_questions')
    if len(reply.split())>case.get('explicit_max_words',100000):failures.append('explicit_length_ignored')
    return list(dict.fromkeys(failures))


def main():
    parser = argparse.ArgumentParser(description="Evaluate sampled Kilas AI Golden responses offline")
    parser.add_argument("responses_json", help="JSON object mapping Golden case IDs to candidate responses")
    parser.add_argument('--professional',action='store_true',help='Check the bounded professional-answer pairs instead of the TSV corpus')
    args = parser.parse_args()
    responses = json.loads(Path(args.responses_json).read_text(encoding="utf-8"))
    if args.professional:
        report={case['id']:evaluate_professional(case,responses.get(case['id'],'')) for case in professional_pairs()}
    else:
        cases = curriculum()
        report = {row["scenario_id"]: evaluate_candidate(cases[row["scenario_id"]],
                  responses.get(row["scenario_id"], "")) for row in golden()}
    print(json.dumps({'label':'Offline fixture red flags only; semantic factuality requires human review',"checked": len(report), "failures": {key: value for key, value in report.items() if value}},
                     ensure_ascii=False, indent=2))
    raise SystemExit(1 if any(report.values()) else 0)


if __name__ == "__main__":
    main()
