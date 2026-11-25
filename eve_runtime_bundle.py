"""Validated Python-only installation into Eve's existing runtime root.

Uses the core's first-party inventory. Never copies config, models or memories.
Install is per-file transactional with rollback, not an atomic live code swap:
quiesce code consumers first. The marker blocks new core imports during a swap.
Already-running Python processes must be restarted separately after readback.
"""
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import eve_store

MANIFEST = '.eve-code-manifest.json'
MARKER = '.eve-code-installing.json'
TRANSACTIONS = '.eve-code-transactions'


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _read(path):
    if int(getattr(path.stat(), 'st_flags', 0)) & 0x40000000:
        raise RuntimeError('Code file is dataless: ' + path.name)
    return path.read_bytes()


def _relative(name):
    path = Path(name)
    if path.is_absolute() or not path.parts or any(p in {'.', '..'} or p.startswith('.') for p in path.parts):
        raise ValueError('Invalid code bundle path')
    if path.suffix != '.py':
        raise ValueError('Only Python code belongs in this bundle')
    return path


def _target(root, relative):
    target = root / relative
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Code target escapes runtime root: ' + str(relative))
    return target


def _put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.code-', dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def _json_put(path, data):
    _put(path, json.dumps(data, sort_keys=True, indent=2).encode())


def _modules(files):
    return {'.'.join(Path(name).with_suffix('').parts).removesuffix('.__init__') for name in files}


def _validate(files):
    modules = _modules(files)
    owned_roots = {m.split('.')[0] for m in modules}
    for name, data in files.items():
        tree = ast.parse(data, filename=name)
        compile(tree, name, 'exec')
        path = Path(name)
        for parent in path.parents:
            if str(parent) != '.' and str(parent / '__init__.py') not in files:
                raise ValueError('Missing package initializer: ' + str(parent))
        for node in ast.walk(tree):
            imports = []
            if isinstance(node, ast.Import):
                imports = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                imports = [node.module]
            for module in imports:
                root = module.split('.')[0]
                if (root in owned_roots or root == 'eve' or root.startswith('eve_')) and module not in modules:
                    raise ValueError('Missing first-party import ' + module + ' in ' + name)


@contextmanager
def prepare(source_root, pairs, *, canary=True):
    """Freeze bytes, validate closure, then import entrypoints from only that copy."""
    source_root = Path(source_root).resolve()
    files, origins = {}, {}
    for name, source, _destination in pairs:
        if Path(name).suffix != '.py':
            continue
        relative = _relative(name)
        source = Path(source)
        if source.is_symlink() or not source.resolve().is_relative_to(source_root):
            raise ValueError('Code source escapes source root')
        if str(relative) in files:
            raise ValueError('Duplicate code path')
        files[str(relative)], origins[str(relative)] = _read(source), source
    if not files:
        raise ValueError('Empty code bundle')
    _validate(files)
    hashes = {name: _hash(data) for name, data in sorted(files.items())}
    manifest = {'schema': 'eve.python_bundle.v1', 'files': hashes,
                'bundle_id': _hash(json.dumps(hashes, sort_keys=True).encode()),
                'state': 'installed_not_activated'}
    with tempfile.TemporaryDirectory(prefix='eve-code-canary-') as temporary:
        stage = Path(temporary) / 'code'
        for name, data in files.items():
            _put(stage / name, data)
        entrypoints = [m for m in ('eve', 'eve_web') if m + '.py' in files]
        if canary and entrypoints:
            home = Path(temporary) / 'home'
            home.mkdir()
            # -I excludes caller PYTHONPATH/user-site; no live config or HOME.
            script = "import sys,importlib\nsys.path.insert(0,sys.argv[1])\n"
            script += "for name in " + repr(entrypoints) + ":\n"
            script += "    module=importlib.import_module(name)\n"
            script += "    if name == 'eve' and hasattr(module, 'build_parser'): module.build_parser()\n"
            environment = {'HOME': str(home), 'USERPROFILE': str(home), 'PATH': os.defpath,
                           'EVE_RUNTIME_DIR': str(home / 'runtime')}
            if os.name == 'nt' and os.environ.get('SystemRoot'):
                environment['SystemRoot'] = os.environ['SystemRoot']
            result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(stage)],
                cwd=temporary, env=environment, capture_output=True, timeout=60)
            if result.returncode:
                # Caller sees error classes/trace, not arbitrary imported stdout.
                raise RuntimeError('Isolated code import failed: ' + result.stderr.decode(errors='replace')[-1800:])
        manifest['canary'] = 'passed' if canary and entrypoints else 'compile_only'
        yield {'files': files, 'origins': origins, 'manifest': manifest}


def _digest_at(path):
    return _hash(_read(path)) if path.exists() else None


def verify(runtime_root):
    runtime = Path(runtime_root)
    if (runtime / MARKER).exists():
        raise RuntimeError('Incomplete code transaction; recover before activation')
    manifest = json.loads(_read(runtime / MANIFEST))
    mismatches = [name for name, digest in manifest['files'].items()
                  if _digest_at(_target(runtime, _relative(name))) != digest]
    return {**manifest, 'verified': not mismatches, 'mismatches': mismatches}


def recover(runtime_root):
    """Rollback one interrupted owned transaction, refusing foreign file changes."""
    runtime = Path(runtime_root)
    with eve_store.file_lock(runtime / 'python-code-install'):
        return _recover_unlocked(runtime)


def _recover_unlocked(runtime):
    marker = runtime / MARKER
    if not marker.exists():
        return {'state': 'no_pending_transaction'}
    record = json.loads(_read(marker))
    transaction = record['transaction']
    if str(uuid.UUID(transaction)) != transaction:
        raise ValueError('Invalid transaction id')
    backup = _target(runtime, Path(TRANSACTIONS) / transaction)
    journal = json.loads(_read(backup / 'journal.json'))
    # Check every destination and backup before restoring even the first file.
    for name, row in journal.items():
        relative = Path(MANIFEST) if name == MANIFEST else _relative(name)
        target = _target(runtime, relative)
        if _digest_at(target) not in {row['old'], row['new']}:
            raise RuntimeError('Concurrent code change prevents rollback: ' + name)
        if row['old'] is not None and _digest_at(backup / 'old' / relative) != row['old']:
            raise RuntimeError('Rollback backup is incomplete: ' + name)
    for name, row in journal.items():
        target = _target(runtime, Path(name))
        if row['old'] is None:
            target.unlink(missing_ok=True)
        else:
            _put(target, _read(backup / 'old' / name))
    marker.unlink()
    return {'state': 'rolled_back', 'transaction': transaction}


def install(runtime_root, candidate):
    runtime = Path(runtime_root)
    runtime.mkdir(parents=True, exist_ok=True)
    with eve_store.file_lock(runtime / 'python-code-install'):
        if (runtime / MARKER).exists():
            raise RuntimeError('Recover the pending code transaction first')
        files = candidate['files']
        manifest = dict(candidate['manifest'], installed_at=time.time())
        for name, source in candidate['origins'].items():
            if _hash(_read(source)) != manifest['files'][name]:
                raise RuntimeError('Source changed after validation: ' + name)
        transaction = str(uuid.uuid4())
        backup = runtime / TRANSACTIONS / transaction
        data = {**files, MANIFEST: json.dumps(manifest, sort_keys=True, indent=2).encode()}
        journal = {}
        for name, content in data.items():
            target = _target(runtime, Path(name))
            old = _read(target) if target.exists() else None
            journal[name] = {'old': _hash(old) if old is not None else None, 'new': _hash(content)}
            if old is not None:
                _put(backup / 'old' / name, old)
        _json_put(backup / 'journal.json', journal)
        # Marker commits only after all rollback bytes are available.
        _json_put(runtime / MARKER, {'transaction': transaction})
        try:
            for name, content in data.items():
                if _digest_at(_target(runtime, Path(name))) != journal[name]['old']:
                    raise RuntimeError('Concurrent code change: ' + name)
                _put(runtime / name, content)
            for name, digest in manifest['files'].items():
                if _digest_at(runtime / name) != digest:
                    raise RuntimeError('Installed digest mismatch: ' + name)
            (runtime / MARKER).unlink()
        except BaseException:
            _recover_unlocked(runtime)
            raise
        return {**verify(runtime), 'transaction': transaction}
