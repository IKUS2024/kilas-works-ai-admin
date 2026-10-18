"""Exact reviewed admission-only compatibility with the fourth actual VM proof.

Never rewrite the original PASS/fingerprint. New execution bytes are fully pinned;
non-gate equivalence is an additional check, never an open-ended AST exemption.
The complete bytes of this verifier are independently pinned in Render config.
"""
import ast
import hashlib
from pathlib import Path

ORIGINAL_PROOF_FINGERPRINT='6aae69eb777df047f9b4dc6891e90dc5a680a2055549eb2c02cc7b0da9b28bad'
BOUNDARY_AST_SHA256='0c9267af9413cc91adcf2c77d761167c5f7eb8ff77a70a2cb3e63acf0e0a2805'
REVIEWED_FILES={'workspace_execution.py': '6f58183fb5d7de0be91ed565063ce579c782e812d2c4de41918f350cb2f79d15', 'workspace_guest.py': '41420460392f80c3b3314b7f254005f5947ae81b550dae7b084dc38c6807dd61', 'workspace_execution_proof.py': '44d57a8f1d0f1ed41918da2c4ea857b55c745976da5e8b62b31eb70510dc3d62', 'workspace_acceptance_fixture.py': '93cd96b652a67c59fad4d14a430c0c9e6f6d4e4b0091c6380bac518e7ceab2ff', 'workspace_execution_access.py': '524652b1a1a5d0341e8b005d0896e279168b4bc633ab815a43f054b2b39cf16d', 'workspace_execution_credits.py': 'b28cc4c849c4c0c78e81e484e2b04e0f06a7ad5d9a10019df770cec616e44285'}


def accepts(outcome):
    if outcome.get('proof_passed') is not True or outcome.get('proof_fingerprint')!=ORIGINAL_PROOF_FINGERPRINT:return False
    root=Path(__file__).parent
    try:
        for name,expected in REVIEWED_FILES.items():
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected:return False
        tree=ast.parse((root/'workspace_execution.py').read_text())
        tree.body=[node for node in tree.body if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) or node.name not in {'accepted','capability'}]
        return hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()==BOUNDARY_AST_SHA256
    except (OSError,ValueError,SyntaxError):return False
