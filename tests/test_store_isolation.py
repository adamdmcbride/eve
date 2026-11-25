import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

import eve

ROOT = Path(eve.__file__).resolve().parent
DURABLE_STORES = ("success_patterns.jsonl", "tensions.jsonl", "experiments.jsonl", "proposals.jsonl", "self_change_ledger.jsonl", "self_change_followups.jsonl", "messages.jsonl", "outcomes.jsonl")


class LiveStoreIsolationTests(unittest.TestCase):
    """The test suite must never write into Eve's durable memory.

    A pattern-lineage fixture wrote two rows into .eve/success_patterns.jsonl on 2026-09-19 while she
    was shut down. Her memory is evidence; a test run is not evidence.
    """

    def test_running_the_loop_suites_leaves_her_durable_stores_untouched(self):
        suites = ["tests.test_experiment_lifecycle", "tests.test_success_pattern_lineage", "tests.test_reflection_trackers", "tests.test_self_change_followup", "tests.test_self_authority", "tests.test_self_change_boundary", "tests.test_core_self_change", "tests.test_architecture_boundaries", "tests.test_core_conversation", "tests.test_conversation_adapter", "tests.test_core_preflight", "tests.test_preflight_adapter"]
        before = {name: self._fingerprint(name) for name in DURABLE_STORES}
        result = subprocess.run([sys.executable, "-m", "unittest", *suites], cwd=str(ROOT), capture_output=True, text=True, timeout=900)
        self.assertEqual(0, result.returncode, result.stderr[-2000:])
        after = {name: self._fingerprint(name) for name in DURABLE_STORES}
        changed = [name for name in DURABLE_STORES if before[name] != after[name]]
        self.assertEqual([], changed, f"these suites wrote into Eve's durable memory: {changed}")

    def test_conversation_finalization_and_entrypoints_have_no_incidental_live_effects(self):
        # Audit hooks cannot be removed: run in a child and fail even if a
        # fixture catches the denied effect. Blocked work is not valid evidence.
        script = '''
import os, sys, unittest
from pathlib import Path
root = Path.cwd()
protected = [root / ".eve", Path.home() / ".eve_runtime"]
blocked = []
def owns(value):
    if not isinstance(value, (str, bytes, os.PathLike)): return False
    path = Path(os.fsdecode(value)).resolve()
    return any(path == base or base in path.parents for base in protected)
def audit(event, args):
    writing, candidates = False, []
    if event == "open":
        mode, flags = args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        candidates = args[:1]
    elif event in {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.symlink", "os.link", "os.truncate", "os.chmod"}:
        writing = True
        candidates = args[:2] if event in {"os.rename", "os.symlink", "os.link"} else args[:1]
    if (writing and any(owns(value) for value in candidates)) or event in {"subprocess.Popen", "socket.connect", "socket.bind"}:
        blocked.append(event)
        raise PermissionError("incidental live effect in conversation fixture: " + event)
names = ["tests.test_core_conversation", "tests.test_conversation_adapter",
         "tests.test_core_preflight", "tests.test_preflight_adapter", "tests.test_reply_intent_routing"]
sys.addaudithook(audit)
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames(names))
print("blocked live effects:", blocked)
raise SystemExit(not result.wasSuccessful() or bool(blocked))
'''
        result = subprocess.run([sys.executable, "-c", script], cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stdout[-1000:] + result.stderr[-2000:])

    def _fingerprint(self, name):
        path = ROOT / ".eve" / name
        if not path.exists():
            return None
        raw = path.read_bytes()
        return hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    unittest.main()
