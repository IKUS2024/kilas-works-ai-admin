"""Local snapshots and patches. Tests require an OS-isolated, networkless sandbox."""
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from . import Result

MAX_BYTES = 5_000_000
SNAPSHOT_BYTES = 20000
SAFE_SUFFIXES = {'.py', '.md', '.txt', '.json', '.csv', '.html', '.css', '.js'}


def root(job):
    return Path(tempfile.gettempdir()) / 'kilas-agent-code' / str(job['id'])


def cleanup(job):
    path = root(job)
    if path.exists():
        shutil.rmtree(path)


def relative(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,160}', value):
        raise ValueError('unsafe_path')
    path = Path(value)
    if value.startswith('/') or path.is_absolute() or '..' in path.parts or any(part.startswith('.') for part in path.parts):
        raise ValueError('unsafe_path')
    if path.suffix not in SAFE_SUFFIXES or re.search(r'(?i)(secret|credential|token|config|key|\.env)', value):
        raise ValueError('protected_file')
    return path


def repositories():
    value = json.loads(os.environ.get('KILAS_AI_CODE_REPOSITORIES', '{}'))
    if not isinstance(value, dict):
        raise ValueError('invalid_repository_configuration')
    return value


def load_snapshot(job):
    import db
    return db.query_one("SELECT a.content FROM kilas_agent_artifacts a JOIN kilas_agent_steps s ON s.id=a.step_id WHERE a.job_id=? AND a.name='_workspace.json' AND s.status='SUCCEEDED' ORDER BY a.id DESC LIMIT 1", (job['id'],))


def prepare(job, alias):
    configured = repositories().get(alias)
    if not configured:
        return None
    source = Path(configured).resolve()
    # Administrators configure local, credential-free source snapshots, never a model URL.
    workspace = root(job)
    marker = workspace / 'repository.json'
    if marker.exists():
        if json.loads(marker.read_text())['alias'] != alias:
            raise ValueError('repository_changed')
        return workspace
    workspace.mkdir(parents=True, exist_ok=True)
    # Cron instances do not promise persistent /tmp. Rehydrate the exact saved snapshot.
    saved = load_snapshot(job)
    if saved:
        state = json.loads(saved['content'])
        if state['alias'] != alias:
            raise ValueError('repository_changed')
        for folder in ('original', 'work'):
            for name, content in state[folder].items():
                target = workspace / folder / relative(name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
        marker.write_text(json.dumps({'alias': alias}))
        return workspace
    if not source.is_dir() or source.is_symlink():
        raise ValueError('invalid_repository')
    total, files, scanned = 0, 0, 0
    try:
        for directory, dirs, names in os.walk(source, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'venv', '__pycache__') and not (Path(directory) / d).is_symlink()]
            for name in names:
                scanned += 1
                if scanned > 2000:
                    raise ValueError('workspace_scan_limit')
                src = Path(directory) / name
                try:
                    rel = relative(src.relative_to(source).as_posix())
                except ValueError:
                    continue
                if src.is_symlink() or src.stat().st_size > 100000:
                    continue
                content = src.read_text(encoding='utf-8')
                if re.search(r'(?i)(BEGIN .*PRIVATE KEY|(?:sk-|AIza|gh[pousr]_)[A-Za-z0-9_-]{20,}|(?:postgres(?:ql)?|mysql|redis)://[^:]+:[^@]+@|(?:password|api_key|secret)\s*=\s*[\x22\x27][^\x22\x27]{8,})', content):
                    continue
                total += len(content.encode())
                files += 1
                if total > MAX_BYTES or files > 400:
                    raise ValueError('workspace_limit')
                for folder in ('original', 'work'):
                    dest = workspace / folder / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(content, encoding='utf-8')
        marker.write_text(json.dumps({'alias': alias}))
        (workspace / 'work').mkdir(exist_ok=True)
        snapshot(workspace)  # Enforce the durable V1 workspace cap before using files.
        return workspace
    except Exception:
        cleanup(job)
        raise


def snapshot(workspace):
    value = {'alias': json.loads((workspace / 'repository.json').read_text())['alias']}
    for folder in ('original', 'work'):
        value[folder] = {p.relative_to(workspace / folder).as_posix(): p.read_text(encoding='utf-8') for p in (workspace / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    content = json.dumps(value, ensure_ascii=False)
    if len(content.encode()) > SNAPSHOT_BYTES:
        raise ValueError('durable_workspace_limit')
    return {'name': '_workspace.json', 'media_type': 'application/json', 'content': content}


def apply_patch(workspace, patch):
    # Structured full-file replacement, not git/shell syntax; validate all files before writing.
    replacements = json.loads(patch)
    if not isinstance(replacements, dict) or not 1 <= len(replacements) <= 8:
        raise ValueError('invalid_patch')
    checked = []
    for name, content in replacements.items():
        path = relative(name)
        if not isinstance(content, str) or len(content.encode()) > 40000:
            raise ValueError('patch_limit')
        target = workspace / 'work' / path
        if target.is_symlink() or workspace.resolve() not in target.resolve().parents:
            raise ValueError('unsafe_path')
        checked.append((target, content))
    size = sum(p.stat().st_size for p in (workspace / 'work').rglob('*') if p.is_file())
    if size + sum(len(content.encode()) for _, content in checked) > MAX_BYTES:
        raise ValueError('workspace_limit')
    for path, content in checked:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')


def diff(workspace):
    parts = []
    paths = {p.relative_to(workspace / folder).as_posix() for folder in ('original', 'work') for p in (workspace / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    for name in sorted(paths):
        old, new = workspace / 'original' / name, workspace / 'work' / name
        parts.extend(difflib.unified_diff(old.read_text().splitlines(True) if old.exists() else [], new.read_text().splitlines(True) if new.exists() else [], fromfile='a/' + name, tofile='b/' + name))
        if sum(len(p) for p in parts) > 24000:
            raise ValueError('diff_too_large')
    return ''.join(parts)


def test_command(workspace):
    bwrap = shutil.which('bwrap')
    python = '/usr/bin/python3' if Path('/usr/bin/python3').is_file() else None
    if not bwrap or not python or os.name != 'posix':
        return None
    # No host home, app root, DB, env, network or production credentials mounted.
    command = [bwrap, '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
               '--ro-bind', '/usr', '/usr', '--ro-bind', '/lib', '/lib']
    for path in ('/lib64', '/bin'):
        if Path(path).exists():
            command += ['--ro-bind', path, path]
    command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                '--ro-bind', str(workspace / 'work'), '/work', '--chdir', '/work',
                '--setenv', 'PATH', '/usr/bin:/bin', python, '-B', '-m', 'unittest', 'discover', '-s', 'tests']
    return command


def resource_limits():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (24000, 24000))
    resource.setrlimit(resource.RLIMIT_NPROC, (128, 128))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def run(job, step, data):
    workspace = prepare(job, data['repo'])
    if workspace is None:
        return Result('WAITING_CAPABILITY', 'Repository belum ada dalam daftar akses coding.', {'reason': 'repository_not_configured'})
    action = step['action']
    if action == 'inspect':
        output = {}
        for name in data['paths']:
            path = workspace / 'work' / relative(name)
            output[name] = path.read_text()[:8000] if path.is_file() else 'File tidak ditemukan.'
        return Result('SUCCEEDED', 'File workspace diperiksa.', {'files': output}, [snapshot(workspace)], verified=True)
    if action == 'patch':
        if data['patch'] == '__GENERATE__':
            from .content_worker import text
            from .. import usage
            key = step['idempotency_key'] + '-patch-' + str(step['attempts'])
            _, operations = usage.reserve(job['user_id'], None, key, 'FAST', 'CHAT')
            success, model, used = False, None, {}
            try:
                if not operations:
                    raise ValueError('duplicate_reservation')
                generated, model, used = text('Propose ONLY JSON object mapping safe relative filenames to complete replacement content. No shell commands, credentials or external actions. Preserve user constraints. Use the inspected files in the checkpoint; fix actual recorded test failures only.\nObjective: ' + job['instruction'] + '\nConstraints: ' + job['constraints_json'] + '\nCheckpoint: ' + job['checkpoint_json'])
                data = {**data, 'patch': generated}
                apply_patch(workspace, generated)
                success = True
            except Exception as error:
                model = getattr(error,'model',None) or model
                used.update(getattr(error,'usage',{}) or {})
                raise
            finally:
                usage.finish(job['user_id'], key, operations, success=success, provider='openai' if success else None, model=model, usage=used)
        else:
            apply_patch(workspace, data['patch'])
    if action == 'test':
        command = test_command(workspace)
        if not command:
            return Result('WAITING_CAPABILITY', 'Sandbox pengujian terisolasi belum tersedia.', {'reason': 'sandbox_not_configured'})
        # Redirect to a bounded file: terminate promptly when output exceeds limit.
        import time
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(command, stdout=log, stderr=log, env={'PATH': '/usr/bin:/bin'}, shell=False, preexec_fn=resource_limits)
            deadline = time.monotonic() + 30
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline or log.tell() > 24000:
                        raise ValueError('test_execution_limit')
                    time.sleep(.05)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            log.seek(0)
            output = log.read(24000).decode('utf-8', errors='replace')
        if not re.search(r'Ran [1-9]\d* tests?', output):
            return Result('FAILED', 'Pengujian belum dijalankan oleh sandbox.',
                          {'exit_code': process.returncode, 'test_output': output, 'reason': 'tests_not_executed'}, verified=False)
        return Result('SUCCEEDED' if process.returncode == 0 else 'FAILED', 'Pengujian berhasil.' if process.returncode == 0 else 'Pengujian gagal.',
                      {'exit_code': process.returncode, 'test_output': output}, [{'name': 'tests.txt', 'media_type': 'text/plain', 'content': output}], verified=True)
    patch = diff(workspace)
    return Result('SUCCEEDED', 'Perubahan lokal tersimpan.' if action == 'patch' else 'Diff workspace disiapkan.',
                  {'diff': patch}, [{'name': 'changes.diff', 'media_type': 'text/plain', 'content': patch}, snapshot(workspace)], verified=True)
