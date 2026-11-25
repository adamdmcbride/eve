#!/usr/bin/env python3
"""Local, derived Graphify code navigation; never execute the indexed source."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.9.92"
SOURCE_DIRS = {"bin", "eve_commands", "eve_core", "eve_adapters", "go", "rust", "mac", "web", "dagster_lab", "script"}
SUFFIXES = {".py", ".swift", ".sh", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".c", ".cpp", ".h", ".m", ".mm"}
SKIP_PARTS = {"tests", "fixtures", "generated", "vendor", "node_modules", "target", "build", "dist", "__pycache__"}
VIS_URL = "https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"
VIS_SHA384 = "Ux6phic9PEHJ38YtrijhkzyJ8yQlH8i/+buBR8s3mAZOJrP1gwyvAcIYl3GWtpX1"
# macOS sys/stat.h; not exposed by every supported Python's stat module.
SF_DATALESS = 0x40000000


def allowed_source(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and bool(path.parts)
        and not any(part.startswith(".") or part in SKIP_PARTS for part in path.parts)
        and (len(path.parts) == 1 or path.parts[0] in SOURCE_DIRS)
        and path.suffix in SUFFIXES
    )


def _read_source_bytes(path: Path) -> bytes:
    if getattr(path.stat(), "st_flags", 0) & SF_DATALESS:
        raise ValueError("Source is a dataless placeholder; make it local before retrying: " + str(path))
    return path.read_bytes()


def source_files(root: Path, include=()) -> dict:
    # New extraction modules need explicit opt-in before their first commit;
    # never expand this to a scan of all untracked files.
    for name in include:
        if not allowed_source(name):
            raise ValueError("Explicit include is outside the source allowlist: " + name)
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    # This helper is intentionally usable before its first commit.
    tracked.append("bin/eve_graphify.py")
    tracked.extend(include)
    result = {}
    for name in sorted(set(filter(allowed_source, tracked))):
        path = root / name
        # Do not follow a tracked symlink (including an ancestor directory).
        parts = PurePosixPath(name).parts
        if any(root.joinpath(*parts[:index]).is_symlink() for index in range(1, len(parts) + 1)):
            continue
        if path.is_file() and path.resolve().is_relative_to(root.resolve()):
            result[name] = hashlib.sha256(_read_source_bytes(path)).hexdigest()
    return result


def local_env() -> dict:
    # No provider keys, proxy settings, model config or inherited PYTHONPATH.
    return {key: os.environ[key] for key in ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL") if key in os.environ}


def graphify_binary() -> str:
    managed = ROOT / ".eve" / "toolchains" / ("graphify-" + VERSION) / "bin" / "graphify"
    binary = str(managed) if managed.is_file() else shutil.which("graphify") or str(Path.home() / ".local" / "bin" / "graphify")
    version = subprocess.check_output([binary, "--version"], env=local_env(), text=True).strip()
    if version != "graphify " + VERSION:
        raise ValueError("Expected graphify " + VERSION + "; reinstall the documented pinned tool.")
    return binary


def run_tool(binary: str, *args: str, cwd: Path, timeout: int = 900) -> None:
    subprocess.run([binary, *args], cwd=cwd, env=local_env(), check=True, timeout=timeout)


def build(root: Path, cache: Path, binary: str, include=None) -> dict:
    started = time.monotonic()
    if include is None:
        previous_manifest = cache / "graphify-out" / "eve_manifest.json"
        include = []
        if previous_manifest.exists():
            include = json.loads(previous_manifest.read_text(encoding="utf-8")).get("explicit_includes", [])
    include = sorted(set(include))
    files = source_files(root, include)
    missing = sorted(set(include) - set(files))
    if missing:
        raise ValueError("Explicit source missing or symlinked: " + ", ".join(missing))
    if not files:
        raise ValueError("No eligible tracked source files.")
    with tempfile.TemporaryDirectory(prefix="build-", dir=cache) as directory:
        work = Path(directory)
        source = work / "source"
        for name, expected_hash in files.items():
            content = _read_source_bytes(root / name)
            if hashlib.sha256(content).hexdigest() != expected_hash:
                raise ValueError("Source changed while staging: " + name)
            dest = source / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        run_tool(binary, "extract", str(source), "--out", str(work), "--code-only", "--no-cluster", "--max-workers", "2", cwd=work)
        graph_dir = work / "graphify-out"
        graph_path = graph_dir / "graph.json"
        raw = json.loads(graph_path.read_text(encoding="utf-8"))
        # The raw extractor omits this flag; undirected clustering can reverse
        # caller/callee endpoints when it serializes the resulting graph.
        raw["directed"] = True
        graph_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        run_tool(binary, "cluster-only", str(work), "--no-label", "--no-viz", cwd=work)
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        if not graph.get("nodes"):
            raise ValueError("Graphify produced an empty graph.")
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "graphify_version": VERSION,
            "checkout": str(root),
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
            "authority": "derived_source_navigation_only",
            "mode": "code-only; no-cluster then cluster-only --no-label --no-viz",
            "files": files,
            "explicit_includes": include,
            "source_file_count": len(files),
            "nodes": len(graph["nodes"]),
            "edges": len(graph.get("links", graph.get("edges", []))),
            "directed": graph.get("directed"),
            "build_seconds": round(time.monotonic() - started, 2),
            "graph_sha256": hashlib.sha256(graph_path.read_bytes()).hexdigest(),
        }
        report = graph_dir / "GRAPH_REPORT.md"
        text = report.read_text(encoding="utf-8")
        text = text.replace(text.splitlines()[0], "# Graph Report - Eve source")
        text = text.replace("Run `git rev-parse HEAD` and compare to check if the graph is stale.", "Run `python3 bin/eve_graphify.py status` to check source hashes, including uncommitted edits.")
        text = text.replace("graphify update .", "python3 bin/eve_graphify.py build")
        report.write_text(text, encoding="utf-8")
        (graph_dir / "eve_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if files != source_files(root, include):
            raise ValueError("Source changed during extraction; rerun build.")
        current = cache / "graphify-out"
        previous = cache / "previous"
        if previous.exists():
            shutil.rmtree(previous)
        if current.exists():
            current.rename(previous)
        try:
            graph_dir.rename(current)
        except OSError:
            if previous.exists():
                previous.rename(current)
            raise
        if previous.exists():
            shutil.rmtree(previous)
    return manifest


def local_html(text: str) -> str:
    start = text.find('<script src="' + VIS_URL + '"')
    end = text.find("</script>", start)
    if start < 0 or end < 0:
        raise ValueError("Unexpected Graphify visualization template; refusing CDN-backed map.")
    return text[:start] + '<script src="../assets/vis-network-9.1.6.min.js"></script>' + text[end + len("</script>"):]


def make_map(cache: Path, binary: str, graph: str) -> Path:
    asset = cache / "assets" / "vis-network-9.1.6.min.js"
    if asset.exists():
        content = asset.read_bytes()
    else:
        # One public dependency download on first map use, never a source upload.
        with urllib.request.urlopen(VIS_URL, timeout=30) as response:
            content = response.read(2_000_001)
    if base64.b64encode(hashlib.sha384(content).digest()).decode() != VIS_SHA384:
        raise ValueError("Visualization library integrity mismatch.")
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(content)
    # Keep the browser view manageable; the query graph remains complete.
    run_tool(binary, "export", "html", "--graph", graph, "--node-limit", "2000", cwd=cache)
    html = cache / "graphify-out" / "graph.html"
    html.write_text(local_html(html.read_text(encoding="utf-8")), encoding="utf-8")
    return html


def graph_status(root: Path, cache: Path) -> dict:
    directory = cache / "graphify-out"
    manifest_path = directory / "eve_manifest.json"
    graph_path = directory / "graph.json"
    if not manifest_path.exists() or not graph_path.exists():
        return {"status": "missing", "next": "python3 bin/eve_graphify.py build"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = source_files(root, manifest.get("explicit_includes", []))
    recorded = manifest["files"]
    changed = sorted(name for name in set(files) | set(recorded) if files.get(name) != recorded.get(name))
    intact = hashlib.sha256(graph_path.read_bytes()).hexdigest() == manifest["graph_sha256"]
    return {
        **{key: value for key, value in manifest.items() if key != "files"},
        "status": "ok" if not changed and intact else "stale",
        "changed_files": changed,
        "graph_intact": intact,
        "graph": str(graph_path),
        "report": str(directory / "GRAPH_REPORT.md"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build").add_argument("--include", action="append", help="Explicit new source file (repeatable); defaults to the last build's includes.")
    for command in ("status", "hubs", "map"):
        commands.add_parser(command)
    for command in ("query", "explain", "affected"):
        commands.add_parser(command).add_argument("text")
    path_parser = commands.add_parser("path")
    path_parser.add_argument("source")
    path_parser.add_argument("target")
    args = parser.parse_args()
    cache = ROOT / ".eve" / "graphify"
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / "tool.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX if args.command in ("build", "map") else fcntl.LOCK_SH)
        if args.command == "build":
            manifest = build(ROOT, cache, graphify_binary(), include=args.include)
            print(json.dumps({key: value for key, value in manifest.items() if key != "files"}, indent=2))
            return 0
        status = graph_status(ROOT, cache)
        if args.command == "status":
            print(json.dumps(status, indent=2))
            return 0 if status["status"] == "ok" else 1
        if status["status"] != "ok":
            raise ValueError("Graph missing/stale/corrupt; run python3 bin/eve_graphify.py build first.")
        if args.command == "map":
            print(make_map(cache, graphify_binary(), status["graph"]))
            return 0
        command = ["god-nodes", "--top", "12"] if args.command == "hubs" else [args.command]
        if args.command == "path":
            command += [args.source, args.target]
        elif args.command != "hubs":
            command += [args.text]
        if args.command == "query":
            command += ["--budget", "2000"]
        run_tool(graphify_binary(), *command, "--graph", status["graph"], cwd=ROOT, timeout=90)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print("Graphify: " + str(exc), file=sys.stderr)
        sys.exit(1)
