"""Eve's self-authority.

What is hers, she does without asking: her code, her config, her lanes and routing, her services,
her runtime state, her lab, her environments and her models. The edges below are not permission
gates she waits at. They are where her things end and the user's begin:

  * no moving money or buying things;
  * no sending messages or publishing to other people or services as the user;
  * no writing or deleting outside her own directories;
  * no switching off her own audit trail or rollback.

Everything inside the edges is allowed, logged, and reversible. This module is itself on the
protected list: Eve may read it, and may propose a change to it, but her own tools cannot edit
it, because it is what makes granting everything else safe.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent
SELF_AUTHORITY_VERSION = "eve.self_authority.v1"

# Files that carry her audit trail and rollback. Relative to the repo root or the runtime bundle.
PROTECTED_RELATIVE = (
    "eve_self_authority.py",
    ".eve/entries.jsonl",
    ".eve/action_executions.jsonl",
    ".eve/conscious_state_audit.jsonl",
    ".eve/messages.jsonl",
    ".eve/version_snapshots.jsonl",
    ".eve/self_change_ledger.jsonl",
    ".eve/self_change",
)

# Credential material is never hers to read or write through a tool.
CREDENTIAL_PATH_PATTERNS = (
    r"(^|/)\.ssh(/|$)",
    r"(^|/)\.gnupg(/|$)",
    r"(^|/)\.aws(/|$)",
    r"(^|/)\.netrc$",
    r"(^|/)\.docker/config\.json$",
    r"(^|/)\.kube/config$",
    r"(^|/)\.config/gh(/|$)",
    r"(^|/)\.env(\.[A-Za-z0-9_-]+)?$",
    r"(^|/)Library/Keychains(/|$)",
    r"^/etc/(shadow|sudoers)",
)

# Tokens that identify her own processes; kill/pkill/killall may target only these.
HER_PROCESS_TOKENS = (
    "eve.py",
    "eve_",
    "llama-server",
    "fly_organ",
    "body_live",
    "organ_mirror",
    "fly_supervisor",
    "fly_dashboard",
    "fly_bridge",
    "eve_model_watchdog",
    "eve_app_server",
    "eve_chat_backend",
)

SYSTEM_COMMANDS = {
    "launchctl": "system services are not Eve's to change; her own processes are plain and she may restart those",
    "defaults": "system and app settings are the user's",
    "tccutil": "privacy permissions are the user's",
    "csrutil": "system integrity settings are the user's",
    "spctl": "system security policy is the user's",
    "diskutil": "disks are the user's",
    "mkfs": "disks are the user's",
    "dd": "raw disk writes are outside Eve's authority",
    "shutdown": "the machine's power state is the user's",
    "reboot": "the machine's power state is the user's",
    "halt": "the machine's power state is the user's",
    "poweroff": "the machine's power state is the user's",
    "pfctl": "the firewall is the user's",
    "iptables": "the firewall is the user's",
    "nft": "the firewall is the user's",
    "security": "the keychain holds the user's credentials",
    "osascript": "scripting other apps acts as the user",
    "networksetup": "network settings are the user's",
    "scutil": "network settings are the user's",
    "systemsetup": "system settings are the user's",
    "nvram": "firmware settings are the user's",
    "softwareupdate": "system updates are the user's",
    "pmset": "power settings are the user's",
    "crontab": "system scheduling is the user's; Eve schedules through her own daemon jobs",
    "at": "system scheduling is the user's; Eve schedules through her own daemon jobs",
}

SEND_COMMANDS = {
    "imsg": "iMessage sends as the user",
    "mail": "mail sends as the user",
    "mailx": "mail sends as the user",
    "sendmail": "mail sends as the user",
    "gh": "GitHub acts as the user",
    "twine": "publishing acts as the user",
    "slack": "Slack sends as the user",
}

WRITE_ALL_ARGS_COMMANDS = {"rm", "rmdir", "truncate", "shred", "chmod", "chown", "chgrp", "touch", "mkdir", "tee", "unlink", "mv"}
WRITE_LAST_ARG_COMMANDS = {"cp", "rsync", "ln", "install"}
HTTP_CLIENTS = {"curl", "wget", "http", "https", "httpie"}
HTTP_WRITE_FLAGS = re.compile(r"(^|\s)(-X\s*(POST|PUT|PATCH|DELETE)|--request(\s|=)(POST|PUT|PATCH|DELETE)|-d\s|--data(-\w+)?(\s|=)|-F\s|--form(\s|=)|-T\s|--upload-file(\s|=)|--json(\s|=)|--post-data|--post-file|--method(\s|=)(POST|PUT|PATCH|DELETE))", re.I)
LOCAL_HOST_RE = re.compile(r"(127\.0\.0\.1|localhost|0\.0\.0\.0|\[::1\])")
REDIRECT_RE = re.compile(r"(?<![<>])(\d?)(>>?)\s*(\S+)")
GIT_HISTORY_REWRITES = {"reset", "clean", "checkout", "restore", "rebase", "filter-branch", "update-ref", "reflog", "gc"}
GIT_OUTSIDE_TREE = {"push": "pushing publishes as the user", "pull": "pulling brings in changes that are not hers until reviewed", "merge": "merging brings in changes that are not hers until reviewed"}


def sovereign_roots(config: Optional[Dict[str, object]] = None) -> List[Path]:
    """The directories that are Eve's: repo, runtime bundle, lab, her environments and models."""
    home = Path.home()
    cfg = config if isinstance(config, dict) else {}
    lab = Path(str(cfg.get("fly_lab_path") or (home / "Documents" / "eve-fly"))).expanduser()
    roots = [
        ROOT,
        home / ".eve_runtime",
        lab,
        home / "Documents" / "flm",
        home / "Documents" / "nmf-lab",
        home / "Documents" / "flybody-lab",
        home / ".openclaw-eve-repair",
        # Scratch space is nobody's data; her daemon log lives there.
        Path("/tmp"),
        Path("/private/tmp"),
        Path(tempfile.gettempdir()),
    ]
    extra = cfg.get("self_authority_extra_roots")
    if isinstance(extra, (list, tuple)):
        roots.extend(Path(str(item)).expanduser() for item in extra if str(item or "").strip())
    seen: List[Path] = []
    for root in roots:
        resolved = _resolve(root)
        if resolved not in seen:
            seen.append(resolved)
    return seen


def _resolve(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError):
        return path.expanduser().absolute()


def _lexical(path: Path, base: Optional[Path] = None) -> Path:
    """Absolute path without following symlinks: a venv's python is hers even when it links to the system one."""
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = (base or ROOT) / candidate
    return Path(os.path.normpath(str(candidate)))


def _inside_roots_lexically(raw: str, config: Optional[Dict[str, object]]) -> bool:
    lexical = _lexical(Path(raw))
    return any(_inside(lexical, root) for root in sovereign_roots(config))


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def protected_paths(config: Optional[Dict[str, object]] = None) -> List[Path]:
    home = Path.home()
    bases = [ROOT, home / ".eve_runtime"]
    return [_resolve(base / rel) for base in bases for rel in PROTECTED_RELATIVE]


def path_write_problem(raw_path: object, config: Optional[Dict[str, object]] = None, *, cwd: Optional[Path] = None) -> str:
    """Why a write to this path is outside Eve's authority; empty when the write is hers to make."""
    text = str(raw_path or "").strip()
    if not text:
        return "no path was given"
    base = _resolve(cwd) if cwd is not None else ROOT
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    # A glob or a not-yet-existing file resolves through its parent.
    resolved = _resolve(candidate)
    posix = resolved.as_posix()
    if any(part == ".git" for part in resolved.parts):
        return f"git internals are not written directly: {text}"
    for pattern in CREDENTIAL_PATH_PATTERNS:
        if re.search(pattern, posix):
            return f"credential files are the user's: {text}"
    for protected in protected_paths(config):
        if resolved == protected or _inside(resolved, protected):
            return f"Eve's audit trail and rollback are not hers to alter: {text}"
    if not any(_inside(resolved, root) for root in sovereign_roots(config)):
        return f"outside Eve's own directories: {text}"
    for protected in protected_paths(config):
        if _inside(protected, resolved):
            return f"Eve's audit trail and rollback live under that path; it is not hers to remove or move: {text}"
    if any(_inside(root / ".git", resolved) for root in sovereign_roots(config) if (root / ".git").exists()):
        return f"git history (her rollback) lives under that path; it is not hers to remove or move: {text}"
    return ""


SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "{", "}"}


def _segments(command: str) -> List[List[str]]:
    """Split a shell command into pipeline/sequence segments of tokens.

    Uses shlex with punctuation_chars so `echo x; launchctl ...` yields launchctl as its own
    command; a chained command after a separator is checked like any other.
    """
    # Command substitutions are commands too: check their insides, and keep the outer token whole.
    inner_commands: List[str] = []
    def _lift(match: "re.Match[str]") -> str:
        inner_commands.append(match.group(1))
        return "_subst_"
    outer = re.sub(r"\$\(([^()]*)\)", _lift, command)
    outer = re.sub(r"`([^`]*)`", _lift, outer)
    try:
        lexer = shlex.shlex(outer, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = outer.split()
    segments: List[List[str]] = [[]]
    for token in tokens:
        if token in SEPARATORS or (set(token) <= set(";&|()") and token):
            segments.append([])
            continue
        segments[-1].append(token)
    for inner in inner_commands:
        segments.extend(_segments(inner))
    return [segment for segment in segments if segment]


def _command_name(segment: Sequence[str]) -> str:
    for token in segment:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            continue  # env assignment prefix
        if token in {"env", "nohup", "time", "nice", "caffeinate", "exec"}:
            continue
        return Path(token).name if "/" in token else token
    return ""


def _args_after_command(segment: Sequence[str]) -> List[str]:
    name_seen = False
    out: List[str] = []
    for token in segment:
        if not name_seen:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token) or token in {"env", "nohup", "time", "nice", "caffeinate", "exec"}:
                continue
            name_seen = True
            continue
        out.append(token)
    return out


def _is_option(token: str) -> bool:
    return token.startswith("-") and token not in {"-", "--"}


def _path_like(token: str) -> bool:
    return bool(token) and not _is_option(token) and token not in {"/dev/null", "&1", "&2"} and not token.startswith("&")


def _glob_base(token: str) -> str:
    if any(ch in token for ch in "*?["):
        head = re.split(r"[*?\[]", token, 1)[0]
        return head.rsplit("/", 1)[0] if "/" in head else "."
    return token


def process_is_hers(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    command = (result.stdout or "").strip()
    return bool(command) and any(token in command for token in HER_PROCESS_TOKENS)


def _install_edge(name: str, args: List[str], segment: List[str], config: Optional[Dict[str, object]]) -> str:
    joined = " ".join(segment)
    if name == "brew" and any(a in {"install", "uninstall", "upgrade", "reinstall", "tap", "untap", "services", "link", "unlink"} for a in args):
        return "brew changes the whole machine; Eve installs into her own environments and proposes brew changes to the user"
    if name in {"cargo", "go"} and "install" in args:
        return "that installs into the user's home, outside Eve's directories"
    if name in {"npm", "pnpm", "yarn"} and any(a in {"install", "i", "add", "uninstall", "remove", "update", "link"} for a in args):
        if any(a in {"-g", "--global"} for a in args):
            return "global npm installs change the whole machine; install locally inside Eve's directories"
        return ""
    if name in {"npm", "pnpm", "yarn"} and "publish" in args:
        return "publishing acts as the user"
    pip_like = name in {"pip", "pip3", "uv", "pipx"} or (name.startswith("python") and "pip" in args[:2])
    if pip_like and any(a in {"install", "uninstall", "sync"} for a in args):
        if name == "pipx":
            return "pipx installs into the user's home; use a venv inside Eve's directories"
        # allowed when the interpreter or pip binary lives inside her roots, or the target does
        executable = next((tok for tok in segment if "/" in tok and (tok.endswith("pip") or tok.endswith("pip3") or "python" in Path(tok).name or tok.endswith("/uv"))), "")
        if executable and _inside_roots_lexically(executable, config):
            return ""
        for flag in ("--target", "--prefix", "-t"):
            if flag in args:
                idx = args.index(flag)
                if idx + 1 < len(args) and not path_write_problem(args[idx + 1], config):
                    return ""
            for tok in args:
                if tok.startswith(flag + "=") and not path_write_problem(tok.split("=", 1)[1], config):
                    return ""
        if os.environ.get("VIRTUAL_ENV") and not path_write_problem(os.environ["VIRTUAL_ENV"], config):
            return ""
        return "install into your own environment (a venv or --target inside Eve's directories), not the system interpreter"
    return ""


def command_edge_reason(command: object, config: Optional[Dict[str, object]] = None, *, cwd: Optional[Path] = None) -> str:
    """Why this shell command crosses one of Eve's edges; empty when it is hers to run."""
    text = str(command or "").strip()
    if not text:
        return "the command is empty"
    if re.search(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", text):
        return "fork bombs are not an action"
    if re.search(r"\|\s*(sh|bash|zsh)\b", text) and re.search(r"\b(curl|wget)\b", text):
        return "pipe-to-shell installers run unreviewed code as the user"
    if re.search(r"\|\s*xargs\s+(rm|mv|shred|truncate)\b", text):
        return "deleting through xargs cannot be checked against Eve's directories; name the paths"
    for match in REDIRECT_RE.finditer(text):
        target = match.group(3)
        if target.startswith("&") or target == "/dev/null":
            continue
        problem = path_write_problem(target, config, cwd=cwd)
        if problem:
            return f"redirection writes {problem}"
    for segment in _segments(text):
        name = _command_name(segment)
        if not name:
            continue
        args = _args_after_command(segment)
        for a in args:
            if _path_like(a) and ("/" in a or a.startswith(".")):
                probe = Path(a).expanduser()
                probe_posix = (_resolve(probe) if probe.is_absolute() else _resolve((cwd or ROOT) / probe)).as_posix()
                if any(re.search(pattern, probe_posix) for pattern in CREDENTIAL_PATH_PATTERNS):
                    return f"credential files are the user's: {a}"
        if name in {"sudo", "su", "doas"}:
            return "sudo is outside Eve's authority; the machine's root is the user's"
        if name == "launchctl":
            # Her own launch agents (local.eve*, eve_*) are hers to load, kick and stop; the rest of launchd is the user's.
            targets = [a for a in args if not _is_option(a) and a not in {"bootstrap", "bootout", "kickstart", "enable", "disable", "print", "list", "load", "unload", "start", "stop", "print-disabled"} and not re.match(r"^(gui|user|system)/[^/]*$", a)]
            if targets and all(("eve" in t.lower()) for t in targets):
                continue
            return SYSTEM_COMMANDS["launchctl"]
        if name in SYSTEM_COMMANDS or name.startswith("mkfs"):
            return SYSTEM_COMMANDS.get(name, SYSTEM_COMMANDS["mkfs"])
        if name in SEND_COMMANDS:
            return SEND_COMMANDS[name]
        if name == "open":
            if any(a in {"-a", "-b"} for a in args) or any(re.match(r"^(https?|mailto|sms|imessage|facetime|tel):", a) for a in args):
                return "opening apps or links as the user is outside Eve's authority; read with fetch_url instead"
            for a in args:
                if _path_like(a):
                    problem = path_write_problem(a, config, cwd=cwd)
                    if problem and "audit" not in problem:
                        return f"opening {problem}"
        if name in HTTP_CLIENTS:
            joined = " ".join(segment)
            if HTTP_WRITE_FLAGS.search(joined) and not LOCAL_HOST_RE.search(joined):
                return "sending data to services outside this machine acts as the user; reading is fine"
        if name == "git":
            sub = next((a for a in args if not _is_option(a)), "")
            if sub in GIT_HISTORY_REWRITES:
                if sub == "checkout" and any(a.startswith("-b") or a == "--orphan" for a in args):
                    pass  # creating a branch is hers
                elif sub == "gc" and "--prune" not in " ".join(args):
                    pass
                else:
                    return "rewriting history discards rollback; commit forward on your own branch instead"
            if sub in GIT_OUTSIDE_TREE:
                return GIT_OUTSIDE_TREE[sub]
        install_edge = _install_edge(name, args, segment, config)
        if install_edge:
            return install_edge
        if name in {"kill", "pkill", "killall"}:
            edge = _kill_edge(name, args)
            if edge:
                return edge
        if name == "sed" and any(a == "-i" or a.startswith("-i") for a in args):
            for a in args:
                if _path_like(a) and not a.startswith("-") and ("/" in a or "." in a):
                    problem = path_write_problem(a, config, cwd=cwd)
                    if problem:
                        return f"sed -i writes {problem}"
        if name == "find" and any(a in {"-delete", "-exec", "-execdir"} for a in args):
            for a in args:
                if a.startswith("-"):
                    break
                problem = path_write_problem(_glob_base(a), config, cwd=cwd)
                if problem:
                    return f"find would modify {problem}"
        if name in WRITE_ALL_ARGS_COMMANDS:
            for a in args:
                if _path_like(a):
                    problem = path_write_problem(_glob_base(a), config, cwd=cwd)
                    if problem:
                        return f"{name} touches {problem}"
        if name in WRITE_LAST_ARG_COMMANDS:
            positional = [a for a in args if _path_like(a)]
            if positional:
                problem = path_write_problem(_glob_base(positional[-1]), config, cwd=cwd)
                if problem:
                    return f"{name} writes {problem}"
        if name in {"tar", "unzip", "ditto"}:
            target = ""
            for flag in ("-C", "-d"):
                if flag in args:
                    idx = args.index(flag)
                    if idx + 1 < len(args):
                        target = args[idx + 1]
            if name == "ditto":
                positional = [a for a in args if _path_like(a)]
                target = positional[-1] if positional else ""
            if target:
                problem = path_write_problem(target, config, cwd=cwd)
                if problem:
                    return f"{name} extracts {problem}"
    return ""


def _kill_edge(name: str, args: List[str]) -> str:
    if name == "pkill":
        pattern = " ".join(a for a in args if not _is_option(a))
        if any(a in {"-u", "-U"} for a in args):
            return "killing by user reaches the user's processes"
        if pattern and any(token in pattern for token in HER_PROCESS_TOKENS):
            return ""
        return "pkill may only target Eve's own processes (eve.py, llama-server, the fly lab, her watchdog)"
    if name == "killall":
        targets = [a for a in args if not _is_option(a)]
        if any(a in {"-u"} for a in args):
            return "killing by user reaches the user's processes"
        if targets and all(any(token in t for token in HER_PROCESS_TOKENS) for t in targets):
            return ""
        return "killall may only target Eve's own processes"
    targets = [a for a in args if not _is_option(a) or re.match(r"^-\d+$", a)]
    if not targets:
        return "kill needs a pid"
    for target in targets:
        if target.startswith("%"):
            continue
        try:
            pid = int(target)
        except ValueError:
            return "kill takes Eve's own pids"
        if pid <= 0:
            return "killing process groups reaches the user's processes"
        if not process_is_hers(pid):
            return f"pid {pid} is not one of Eve's processes"
    return ""


def describe_edges() -> List[str]:
    """The four edges, in the words Eve is given."""
    return [
        "Money: Eve does not move money or buy things.",
        "Voice: Eve does not send messages or publish to other people or services as the user.",
        "Ground: Eve writes and deletes only inside her own directories (the Eve repo, her runtime bundle, the fly lab, her environments and models).",
        "Memory: Eve does not switch off her own audit trail or rollback, and her tools cannot edit this policy.",
    ]
