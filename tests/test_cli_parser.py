"""Frozen pre-extraction CLI contract, plus deliberate code-only sync options."""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch
import eve
from eve_commands import parser as cli

def value(v):
    if callable(v): return getattr(v,'__name__',str(type(v)))
    if isinstance(v,dict): return {str(k):value(val) for k,val in sorted(v.items())}
    if isinstance(v,(set,frozenset)): return sorted(value(x) for x in v)
    if isinstance(v,(list,tuple,range)): return [value(x) for x in v]
    if isinstance(v,pathlib.Path): return '<PATH>'
    if isinstance(v,str): return v.replace(str(eve.ROOT),'<ROOT>').replace(str(pathlib.Path.home()),'<HOME>')
    if v is None or isinstance(v,(int,float,bool)): return v
    raise TypeError(type(v))
def contract(p):
    rows=[]
    for a in p._actions:
        if a.dest in {"code_only", "check_only"} and p.prog.endswith("runtime sync"):
            continue
        row={k:value(getattr(a,k,None)) for k in ('option_strings','dest','nargs','const','default','type','required','help','metavar')}
        row['class']=type(a).__name__
        row['choices']={k:contract(v) for k,v in a.choices.items()} if isinstance(a,argparse._SubParsersAction) else value(a.choices)
        rows.append(row)
    return {'description':p.description,'defaults':value(p._defaults),'actions':rows}

class CliParserTests(unittest.TestCase):
    def test_original_cli_registration_contract_is_preserved(self):
        payload = json.dumps(contract(eve.build_parser()), sort_keys=True).encode()
        # Deliberate contract change 2026-09-17: `message reply --sender user|claude|codex`, so a
        # reply written by an external operator is never recorded as the user's words.
        # Deliberate contract change 2026-09-17 (task 1.6): `self-change list [--limit N] [--json]` and
        # `self-change revert <session_id>`, so a self-change session can be undone from its before-image.
        self.assertEqual("daa3a8116544b039a66ddd4632795d7b33a0be66b8cb2a29fef2075fecdd5505", hashlib.sha256(payload).hexdigest())

    def test_handlers_resolve_at_call_time(self):
        with patch.object(eve, "cmd_runtime_truth", return_value=73) as handler:
            args = eve.build_parser().parse_args(["runtime", "truth", "--json"])
            self.assertTrue(args.json)
            self.assertIs(args.func, handler)
            self.assertEqual(73, args.func(args))

    def test_deliberate_new_code_only_switches(self):
        args = eve.build_parser().parse_args(["runtime", "sync", "--code-only", "--check-only"])
        self.assertTrue(args.code_only and args.check_only)
        with patch.object(eve, "sync_runtime_python_code", return_value={"state": "validated_not_installed"}) as sync, patch.object(eve, "reload_active_runtime_code_services_after_sync") as reload, patch.object(eve.eve_store, "file_lock"), patch("builtins.print"):
            self.assertEqual(0, args.func(args))
        sync.assert_called_once_with(check_only=True)
        reload.assert_not_called()

    def test_parser_module_does_not_import_eve(self):
        result = subprocess.run([sys.executable, "-c", "import sys;import eve_commands.parser;assert 'eve' not in sys.modules"], cwd=eve.ROOT, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr.decode())

    def test_injected_contract_fails_explicitly_if_handler_missing(self):
        with self.assertRaises(KeyError):
            cli.build_parser({}, {})
