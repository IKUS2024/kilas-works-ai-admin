"""Exact reviewed admission-only compatibility with the fourth actual VM proof.

Never rewrite the original PASS/fingerprint. New execution bytes are fully pinned;
non-gate equivalence is an additional check, never an open-ended AST exemption.
The complete bytes of this verifier are independently pinned in Render config.
"""
import ast
import hashlib
from pathlib import Path

ORIGINAL_PROOF_FINGERPRINT='6aae69eb777df047f9b4dc6891e90dc5a680a2055549eb2c02cc7b0da9b28bad'
BOUNDARY_SOURCE_SHA256='0a31b1ae569466aac9ed192072ff5b0f7995b40ca0ceb6f6cb0e0f649a88fcf2'
REVIEWED_FILES={'workspace_execution.py': '6f58183fb5d7de0be91ed565063ce579c782e812d2c4de41918f350cb2f79d15', 'workspace_guest.py': '41420460392f80c3b3314b7f254005f5947ae81b550dae7b084dc38c6807dd61', 'workspace_execution_proof.py': '44d57a8f1d0f1ed41918da2c4ea857b55c745976da5e8b62b31eb70510dc3d62', 'workspace_acceptance_fixture.py': '93cd96b652a67c59fad4d14a430c0c9e6f6d4e4b0091c6380bac518e7ceab2ff', 'workspace_execution_access.py': '96c5e5a057155db4385fcaf54e6e693652564450881be5ab03e54b264d5c8277', 'workspace_execution_credits.py': 'b28cc4c849c4c0c78e81e484e2b04e0f06a7ad5d9a10019df770cec616e44285'}


def boundary_source(source):
    # Line spans only: hash exact remaining source bytes, never version-specific
    # ast.dump fields/defaults. Full-file pins above also protect BOTH removed gates.
    lines=source.splitlines(keepends=True);excluded=set()
    for node in ast.parse(source).body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'accepted','capability'}:
            excluded.update(range(node.lineno-1,node.end_lineno))
    return hashlib.sha256(''.join(line for index,line in enumerate(lines) if index not in excluded).encode()).hexdigest()


def diagnostic_reason(outcome):
    if outcome.get('proof_passed') is not True or outcome.get('proof_fingerprint')!=ORIGINAL_PROOF_FINGERPRINT:return 'original_proof_mismatch'
    root=Path(__file__).parent
    try:
        for name,expected in REVIEWED_FILES.items():
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:return 'source_mismatch:'+name
        if boundary_source((root/'workspace_execution.py').read_text())!=BOUNDARY_SOURCE_SHA256:return 'boundary_source_mismatch'
        return 'matched'
    except (OSError,ValueError,SyntaxError):return 'source_unreadable'


def accepts(outcome):
    return diagnostic_reason(outcome)=='matched'
