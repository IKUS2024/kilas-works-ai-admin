"""Offline recipe contracts only. No E2B build, VM or credential access."""
import ast,hashlib,importlib.util,io,json,re,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]/'sandbox-templates/kilas-documents-v1'


class PlanTests(unittest.TestCase):
    def test_complete_exact_hash_lock_and_abi_plan(self):
        plan=json.loads((ROOT/'plan.json').read_text());lines=[line for line in (ROOT/'requirements.lock').read_text().splitlines() if line and not line.startswith('#')]
        expected={f"{w['name']}=={w['version']} --hash=sha256:{w['sha256']}" for w in plan['wheels']}
        self.assertEqual(set(lines),expected);self.assertEqual(len(lines),10)
        for wheel in plan['wheels']:self.assertRegex(wheel['sha256'],'^[0-9a-f]{64}$');self.assertNotIn('.tar',wheel['wheel'])
        self.assertEqual(plan['base_image'],'docker.io/library/python@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a')
        self.assertEqual(plan['python_version'],'3.12.14');self.assertEqual(plan['python_major_minor'],'3.12');self.assertEqual(plan['interpreter'],'/opt/kilas-document-python/bin/python3')
        self.assertEqual(plan['source_interpreter'],'/usr/local/bin/python3.12')
    def test_immutable_base_required_and_definition_cannot_provision(self):
        spec=importlib.util.spec_from_file_location('prepared_template',ROOT/'template.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for value in (None,'base','e2bdev/base:latest','repo; echo bad'):
            with self.assertRaisesRegex(ValueError,'immutable_base'):module.definition(value)
        import e2b
        with patch.object(e2b.Template,'build',side_effect=AssertionError('remote build forbidden')),patch.object(e2b.Sandbox,'create',side_effect=AssertionError('VM forbidden')):
            with self.assertRaisesRegex(ValueError,'unreviewed_base'):module.definition('e2bdev/base@sha256:'+'0'*64)
            self.assertIsNotNone(module.definition(json.loads((ROOT/'plan.json').read_text())['base_image']))
        tree=ast.parse((ROOT/'template.py').read_text())
        self.assertFalse(any(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('build','build_in_background','create') for node in ast.walk(tree)))
        self.assertIn('--require-hashes',module.INSTALL);self.assertIn('--only-binary=:all:',module.INSTALL);self.assertIn('chown -R 0:0',module.INSTALL)
    def test_no_runtime_or_acceptance_gate_changes_and_fixed_context(self):
        source=(ROOT/'template.py').read_text()
        for name in ('requirements.lock','plan.json','verify_runtime.py','smoke_documents.py'):self.assertIn(repr(name),source)
        self.assertNotIn('E2B_API_KEY',source);self.assertNotIn('KILAS_LARGE_PROOF_APPROVAL',source)
        self.assertIn("user='nobody'",source);self.assertIn("user='root',mode=0o644",source)
        self.assertIn(' -I -B ',source)

    def test_representative_pdf_pptx_are_real_small_and_large_files(self):
        spec=importlib.util.spec_from_file_location('fixed_smoke',ROOT/'smoke_documents.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        from pypdf import PdfReader
        from pptx import Presentation
        files=module.representative();self.assertEqual(len(files),4);self.assertLessEqual(sum(map(len,files.values())),16777216)
        for name,raw in files.items():
            self.assertLessEqual(len(raw),8388608)
            if name.startswith('small.'):self.assertLessEqual(len(raw),65536)
            else:self.assertGreater(len(raw),65536)
            if name.endswith('.pdf'):
                pages=PdfReader(io.BytesIO(raw),strict=True).pages
                self.assertEqual(len(pages),1 if name.startswith('small.') else 12)
                self.assertTrue(all('184000' in page.extract_text() for page in pages))
            else:self.assertEqual(len(Presentation(io.BytesIO(raw)).slides),1 if name.startswith('small.') else 15)

    def test_exact_patch_version_and_offline_local_root_owned_recipe(self):
        spec=importlib.util.spec_from_file_location('fixed_verifier',ROOT/'verify_runtime.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with patch.object(module.platform,'python_version',return_value='3.12.13'):
            with self.assertRaises(AssertionError):module.verify('/does-not-exist')
        docker=(ROOT/'Dockerfile.local').read_text()
        self.assertIn(json.loads((ROOT/'plan.json').read_text())['base_image'],docker)
        self.assertIn('--no-index',docker);self.assertIn('--require-hashes',docker);self.assertIn('USER nobody',docker)
        self.assertIn('--smoke --representative',docker)


if __name__=='__main__':unittest.main()
