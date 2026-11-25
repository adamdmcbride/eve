"""Portable installer and download artifact construction for Eve.

This module owns packaging bytes and install-page presentation only. It does not
start services, select models or lanes, mutate Eve state, or grant action
authority. ``eve_web`` re-exports these names while retaining HTTP routing.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from html import escape as html_escape
from pathlib import Path

import eve
import eve_http_query
import eve_http_security
import eve_profile


ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT / "bin"
MAC_INSTALLER_VERSION = "2026-04-21c"
MAC_INSTALLER_FILENAME = f"EveMacInstaller-{MAC_INSTALLER_VERSION}.zip"
MAC_INSTALLER_APP_NAME = f"Eve Installer {MAC_INSTALLER_VERSION}.app"


def trusted_installer_endpoint(primary_host: object, api_port: object) -> tuple[str, int]:
    """Validate values before placing them in an installer or update artifact."""

    return (
        eve_http_security.require_advertised_host(primary_host, label="primary host"),
        eve_http_security.require_network_port(api_port, label="primary API port"),
    )


def advertised_endpoint_query(
    query: eve_http_query.BoundedQuery,
    *,
    default_host: object,
    default_api_port: object,
    default_model_port: object = 11434,
) -> tuple[str, int, int]:
    """Parse endpoint query copies without granting request-owned authority."""

    configured_host, configured_api_port = trusted_installer_endpoint(
        default_host,
        default_api_port,
    )
    primary_host = eve_http_security.require_advertised_host(
        query.value(
            "host",
            default=str(default_host),
            maximum_characters=253,
            strip=False,
        ),
        label="host",
    )
    api_port = eve_http_security.require_network_port(
        query.value(
            "api_port",
            default=str(default_api_port),
            maximum_characters=5,
            strip=False,
        ),
        label="api_port",
    )
    if primary_host != configured_host:
        raise ValueError("host must match Eve's configured advertised host")
    if api_port != configured_api_port:
        raise ValueError("api_port must match Eve's listening API port")
    model_port = eve_http_security.require_network_port(
        query.value(
            "ollama_port",
            default=str(default_model_port),
            maximum_characters=5,
            strip=False,
        ),
        label="ollama_port",
    )
    return configured_host, configured_api_port, model_port


def customized_windows_script(filename: str, primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    path = BIN_DIR / filename
    if not path.exists():
        raise FileNotFoundError(filename)
    text = path.read_text(encoding="utf-8")
    host_value = primary_host.replace('"', "`\"")
    if filename == "install_windows_eve.ps1":
        text = text.replace('[string]$PrimaryHost = "",', f'[string]$PrimaryHost = "{host_value}",', 1)
    elif filename == "update_windows_eve.ps1":
        text = text.replace('[Parameter(Mandatory = $true)][string]$PrimaryHost,', f'[string]$PrimaryHost = "{host_value}",', 1)
    text = text.replace('[int]$PrimaryApiPort = 8787,', f"[int]$PrimaryApiPort = {int(api_port)},", 1)
    return text.encode("utf-8")


def customized_windows_launcher(filename: str, primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    base_url = f"http://{eve_http_security.http_authority(primary_host, api_port)}"
    if filename == "install_windows_eve.cmd":
        script_name = "install_windows_eve.ps1"
        script_args = ""
    elif filename == "update_windows_eve.cmd":
        script_name = "update_windows_eve.ps1"
        script_args = " -IncludeCode -IncludeApp -AutoRestart -InstallAutoUpdateTask"
    else:
        raise FileNotFoundError(filename)
    script_url = f"{base_url}/downloads/{script_name}"
    launcher = f"""@echo off
setlocal
set "EVE_TMP=%TEMP%\\{script_name}"
echo Downloading Eve installer from {base_url}...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -UseBasicParsing '{script_url}' -OutFile $env:TEMP+'\\{script_name}'"
if errorlevel 1 (
  echo Failed to download {script_name}
  pause
  exit /b 1
)
echo Running {script_name}...
powershell -NoProfile -ExecutionPolicy Bypass -File "%EVE_TMP%"{script_args}
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo Eve installer exited with code %EXITCODE%
  pause
)
exit /b %EXITCODE%
"""
    return launcher.encode("utf-8")


def build_unix_installer_script(platform_name: str, primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    if platform_name not in {"macos", "linux"}:
        raise ValueError(f"Unsupported platform installer: {platform_name}")
    host_literal = json.dumps(primary_host)
    install_root = "${HOME}/Applications/Eve" if platform_name == "macos" else "${HOME}/.local/share/eve"
    daemon_step = 'python3 eve.py daemon install || true'
    ollama_start = """\
start_ollama() {
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    return 0
  fi
"""
    if platform_name == "macos":
        platform_title = "macOS"
        script_name = "Install Eve.command"
        shell = "#!/bin/zsh"
        ollama_install = """\
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  if command -v brew >/dev/null 2>&1; then
    brew install ollama || true
  fi
fi
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
"""
        ollama_start += """\
  if command -v brew >/dev/null 2>&1; then
    brew services start ollama >/dev/null 2>&1 || true
  fi
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    nohup ollama serve >/tmp/eve_ollama_install.log 2>&1 &
  fi
"""
    else:
        platform_title = "Linux"
        script_name = "install_linux_eve.sh"
        shell = "#!/usr/bin/env bash"
        ollama_install = """\
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
"""
        ollama_start += """\
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user start ollama >/dev/null 2>&1 || true
  fi
  if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    nohup ollama serve >/tmp/eve_ollama_install.log 2>&1 &
  fi
"""
    ollama_start += """\
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Ollama did not start in time."
  return 1
}
"""
    script = f"""{shell}
set -euo pipefail

PRIMARY_HOST={host_literal}
PRIMARY_API_PORT={int(api_port)}
PRIMARY_OLLAMA_PORT=11434
BASE_URL="http://${{PRIMARY_HOST}}:${{PRIMARY_API_PORT}}"
INSTALL_ROOT="{install_root}"
TMP_DIR="$(mktemp -d)"
CODE_BUNDLE_PATH="${{TMP_DIR}}/eve_code_bundle.zip"

cleanup() {{
  rm -rf "${{TMP_DIR}}"
}}
trap cleanup EXIT

require_command() {{
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}}

require_command curl
require_command python3

mkdir -p "${{INSTALL_ROOT}}"

echo "Downloading Eve code bundle from ${{BASE_URL}}..."
curl -fsSL "${{BASE_URL}}/api/code-bundle" -o "${{CODE_BUNDLE_PATH}}"

python3 - "${{CODE_BUNDLE_PATH}}" "${{INSTALL_ROOT}}" <<'PY'
import pathlib
import sys
import zipfile

archive_path = pathlib.Path(sys.argv[1])
install_root = pathlib.Path(sys.argv[2])
install_root.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive_path, "r") as archive:
    archive.extractall(install_root)
PY

cd "${{INSTALL_ROOT}}"

echo "Eve {platform_title} installer version: {MAC_INSTALLER_VERSION}"

echo "Initializing Eve..."
python3 eve.py init

echo "Pulling Eve bootstrap state from ${{BASE_URL}} using the primary host..."
python3 eve.py bootstrap pull --host "${{PRIMARY_HOST}}" --api-port "${{PRIMARY_API_PORT}}" --ollama-port "${{PRIMARY_OLLAMA_PORT}}" --use-primary-ollama

if [ "${{EVE_ENABLE_LOCAL_OLLAMA:-0}}" = "1" ]; then
{ollama_install}
{ollama_start}
  echo "Starting local Ollama because EVE_ENABLE_LOCAL_OLLAMA=1..."
  if start_ollama; then
    echo "Switching Eve to local Ollama and pulling models..."
    if python3 eve.py bootstrap pull --host "${{PRIMARY_HOST}}" --api-port "${{PRIMARY_API_PORT}}" --ollama-port "${{PRIMARY_OLLAMA_PORT}}" --pull-models; then
      echo "Eve is now configured to use local Ollama."
    else
      echo "Local model pull failed; Eve will stay pointed at the primary Ollama host for now."
      python3 eve.py bootstrap pull --host "${{PRIMARY_HOST}}" --api-port "${{PRIMARY_API_PORT}}" --ollama-port "${{PRIMARY_OLLAMA_PORT}}" --use-primary-ollama
    fi
  else
    echo "Local Ollama did not come up; Eve will stay pointed at the primary Ollama host for now."
  fi
else
  echo "Skipping automatic local Ollama startup. Set EVE_ENABLE_LOCAL_OLLAMA=1 if you want the installer to turn it on."
fi

echo "Installing Eve background service..."
{daemon_step}

echo "Running Eve doctor..."
if ! python3 eve.py doctor; then
  echo "Doctor reported a problem, but the install can still continue."
fi

echo
echo "Eve {platform_title} install completed at ${{INSTALL_ROOT}}."
"""
    return script.encode("utf-8")


def build_macos_installer_bundle(primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    stream = io.BytesIO()
    script_name = "Install Eve.command"
    readme = f"""Eve macOS Setup

1. Open {script_name}
2. Approve Terminal/network prompts if macOS asks
3. The installer will fetch Eve from http://{primary_host}:{int(api_port)}

Installer version: {MAC_INSTALLER_VERSION}
"""
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        script_info = zipfile.ZipInfo(script_name)
        script_info.external_attr = 0o755 << 16
        archive.writestr(script_info, build_unix_installer_script("macos", primary_host, api_port))
        readme_info = zipfile.ZipInfo("README.txt")
        readme_info.external_attr = 0o644 << 16
        archive.writestr(readme_info, readme.encode("utf-8"))
    return stream.getvalue()


def build_macos_installer_app_bundle(primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    app_name = MAC_INSTALLER_APP_NAME
    launcher_script = """#!/bin/zsh
set -euo pipefail

RESOURCE_DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
INSTALL_SCRIPT="${RESOURCE_DIR}/Install Eve.command"
chmod +x "${INSTALL_SCRIPT}"

osascript <<OSA
tell application "Terminal"
  activate
  do script quoted form of POSIX path of "${INSTALL_SCRIPT}"
end tell
OSA
"""
    installer_bundle_id = eve_profile.app_bundle_identifier("installer", MAC_INSTALLER_VERSION)
    info_plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleExecutable</key>
  <string>Eve Installer {MAC_INSTALLER_VERSION}</string>
  <key>CFBundleIconFile</key>
  <string>eve</string>
  <key>CFBundleIdentifier</key>
  <string>{installer_bundle_id}</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Eve Installer {MAC_INSTALLER_VERSION}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>{MAC_INSTALLER_VERSION}</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
</dict>
</plist>
"""
    readme = f"""Eve macOS Installer App

1. Open Eve Installer.app
2. Terminal will launch the installer
3. The installer will fetch Eve from http://{primary_host}:{int(api_port)}

Installer version: {MAC_INSTALLER_VERSION}
"""
    with tempfile.TemporaryDirectory(prefix="eve-mac-installer-") as temp_dir:
        root = Path(temp_dir)
        app_root = root / app_name
        contents_dir = app_root / "Contents"
        macos_dir = contents_dir / "MacOS"
        resources_dir = contents_dir / "Resources"
        macos_dir.mkdir(parents=True, exist_ok=True)
        resources_dir.mkdir(parents=True, exist_ok=True)

        launcher_path = macos_dir / "Eve Installer"
        launcher_path.write_text(launcher_script, encoding="utf-8")
        launcher_path.chmod(0o755)

        installer_script_path = resources_dir / "Install Eve.command"
        installer_script_path.write_bytes(build_unix_installer_script("macos", primary_host, api_port))
        installer_script_path.chmod(0o755)

        (contents_dir / "Info.plist").write_text(info_plist, encoding="utf-8")
        (resources_dir / "README.txt").write_text(readme, encoding="utf-8")

        icon_path = ROOT / "mac" / "generated" / "eve.icns"
        if icon_path.exists():
            shutil.copy2(icon_path, resources_dir / "eve.icns")

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(app_root.rglob("*")):
                if not path.is_file():
                    continue
                archive.write(path, path.relative_to(root).as_posix())
        return stream.getvalue()


def build_linux_installer_bundle(primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    stream = io.BytesIO()
    script_name = "install_linux_eve.sh"
    readme = f"""Eve Linux Setup

1. Extract this archive
2. Run ./{script_name}
3. The installer will fetch Eve from http://{primary_host}:{int(api_port)}
"""
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        script_bytes = build_unix_installer_script("linux", primary_host, api_port)
        script_info = tarfile.TarInfo(script_name)
        script_info.size = len(script_bytes)
        script_info.mode = 0o755
        archive.addfile(script_info, io.BytesIO(script_bytes))

        readme_bytes = readme.encode("utf-8")
        readme_info = tarfile.TarInfo("README.txt")
        readme_info.size = len(readme_bytes)
        readme_info.mode = 0o644
        archive.addfile(readme_info, io.BytesIO(readme_bytes))
    return stream.getvalue()


def stage_windows_installer_payload(staging_dir: Path, primary_host: str, api_port: int) -> None:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    for relative in eve.iter_code_bundle_paths():
        source = ROOT / relative
        destination = staging_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    install_script = staging_dir / "bin" / "install_windows_eve.ps1"
    update_script = staging_dir / "bin" / "update_windows_eve.ps1"
    install_script.write_bytes(customized_windows_script("install_windows_eve.ps1", primary_host, api_port))
    update_script.write_bytes(customized_windows_script("update_windows_eve.ps1", primary_host, api_port))

    updater_cmd = (
        '@echo off\r\n'
        'setlocal\r\n'
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bin\\update_windows_eve.ps1" -IncludeCode -IncludeApp -AutoRestart -InstallAutoUpdateTask\r\n'
    )
    (staging_dir / "Update Eve.cmd").write_text(updater_cmd, encoding="utf-8")


def build_windows_installer_script(payload_dir: Path, output_exe: Path, primary_host: str, api_port: int) -> str:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    output_path = str(output_exe).replace("/", "\\")
    payload_path = str(payload_dir).replace("/", "\\")
    install_args = (
        f'-NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\\bin\\install_windows_eve.ps1" '
        f'-ProjectRoot "$INSTDIR" -PrimaryHost "{primary_host}" -PrimaryApiPort {int(api_port)} -PullModels'
    )
    return f"""\
Unicode True
!include "LogicLib.nsh"
Name "Eve"
OutFile "{output_path}"
InstallDir "$LOCALAPPDATA\\Eve"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
ShowUninstDetails show

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "{payload_path}\\*"
  WriteUninstaller "$INSTDIR\\Uninstall Eve.exe"
  CreateDirectory "$SMPROGRAMS\\Eve"
  CreateShortCut "$SMPROGRAMS\\Eve\\Update Eve.lnk" "$INSTDIR\\Update Eve.cmd"
  CreateShortCut "$DESKTOP\\Update Eve.lnk" "$INSTDIR\\Update Eve.cmd"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Eve" "DisplayName" "Eve"
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Eve" "UninstallString" "$INSTDIR\\Uninstall Eve.exe"
  ClearErrors
  ExecWait '"$SYSDIR\\WindowsPowerShell\\v1.0\\powershell.exe" {install_args}' $0
  ${{If}} $0 != 0
    MessageBox MB_ICONEXCLAMATION|MB_OK "Eve copied its files, but the bootstrap step returned exit code $0. You can retry with $INSTDIR\\bin\\install_windows_eve.ps1."
  ${{EndIf}}
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\\Update Eve.lnk"
  Delete "$SMPROGRAMS\\Eve\\Update Eve.lnk"
  RMDir "$SMPROGRAMS\\Eve"
  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Eve"
  Delete "$INSTDIR\\Uninstall Eve.exe"
  RMDir /r "$INSTDIR"
SectionEnd
"""


def build_windows_installer_exe(primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    with tempfile.TemporaryDirectory(prefix="eve-installer-") as temp_dir:
        root = Path(temp_dir)
        payload_dir = root / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        stage_windows_installer_payload(payload_dir, primary_host, api_port)
        output_exe = root / "EveSetup.exe"
        script_path = root / "EveSetup.nsi"
        script_path.write_text(
            build_windows_installer_script(payload_dir, output_exe, primary_host, api_port),
            encoding="utf-8",
        )
        result = subprocess.run(
            ["makensis", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0 or not output_exe.exists():
            detail = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
            raise RuntimeError(f"Could not build Windows installer.\n{detail.strip()}")
        return output_exe.read_bytes()


def build_windows_app_package_archive(primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    stream = io.BytesIO()
    with tempfile.TemporaryDirectory(prefix="eve-winpkg-") as temp_dir:
        payload_dir = Path(temp_dir) / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        stage_windows_installer_payload(payload_dir, primary_host, api_port)
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(payload_dir.rglob("*")):
                if not path.is_file():
                    continue
                archive.write(path, path.relative_to(payload_dir).as_posix())
    return stream.getvalue()


def render_windows_install_page(base_url: str, primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    base_url = f"http://{eve_http_security.http_authority(primary_host, api_port)}"
    installer_exe_url = f"{base_url}/downloads/EveSetup.exe"
    install_url = f"{base_url}/downloads/install_windows_eve.cmd"
    update_url = f"{base_url}/downloads/update_windows_eve.cmd"
    bootstrap_url = f"{base_url}/downloads/bootstrap_bundle.json"
    code_url = f"{base_url}/downloads/code-bundle.zip"
    app_package_url = f"{base_url}/downloads/EveWindowsAppPackage.zip"
    install_command = "EveSetup.exe"
    update_command = (
        f"update_windows_eve.cmd"
    )
    advanced_install_command = (
        f"powershell -ExecutionPolicy Bypass -File .\\install_windows_eve.ps1 "
        f"-PrimaryHost {primary_host} -PrimaryApiPort {api_port} -PullModels"
    )
    advanced_update_command = (
        f"powershell -ExecutionPolicy Bypass -File .\\update_windows_eve.ps1 "
        f"-PrimaryHost {primary_host} -PrimaryApiPort {api_port} -IncludeCode -IncludeApp -AutoRestart"
    )
    html = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Eve Windows Prototype</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f0e7;
      --card: #fffaf2;
      --ink: #1c1a17;
      --muted: #6f6456;
      --line: #d8c8b4;
      --accent: #0b6e4f;
      --accent-2: #d96c2d;
    }}
    body {{ margin: 0; font-family: Georgia, "Iowan Old Style", serif; background: radial-gradient(circle at top, #fff9ef, var(--bg)); color: var(--ink); }}
    main {{ max-width: 920px; margin: 0 auto; padding: 40px 20px 64px; }}
    .hero {{ padding: 28px; border: 1px solid var(--line); background: linear-gradient(135deg, rgba(11,110,79,.08), rgba(217,108,45,.10)); border-radius: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-top: 20px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 18px; padding: 18px; }}
    a.button {{ display: inline-block; margin-top: 10px; padding: 10px 14px; border-radius: 999px; background: var(--accent); color: #fffaf2; text-decoration: none; font-weight: 600; }}
    a.secondary {{ background: var(--accent-2); }}
    code, pre {{ font-family: "SFMono-Regular", Consolas, monospace; }}
    pre {{ white-space: pre-wrap; background: #f2eadf; border-radius: 14px; padding: 14px; border: 1px solid var(--line); overflow-x: auto; }}
    p.meta {{ color: var(--muted); }}
    ul {{ padding-left: 20px; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <p class="meta">Primary Eve host: {html_escape(primary_host)}:{api_port}</p>
      <h1>Windows Eve Prototype</h1>
      <p>Use this page from the Windows browser to download the installer, updater, bootstrap bundle, or the current application code bundle directly from this Mac.</p>
    </section>
    <section class="grid">
      <div class="card">
        <h2>Installer</h2>
        <p>Downloads a real Windows installer executable that already knows how to connect back to this Mac.</p>
        <a class="button" href="{html_escape(installer_exe_url)}">Download EveSetup.exe</a>
      </div>
      <div class="card">
        <h2>Updater</h2>
        <p>Downloads a Windows launcher for later updates from this Mac.</p>
        <a class="button secondary" href="{html_escape(update_url)}">Download Easy Updater</a>
      </div>
      <div class="card">
        <h2>Bootstrap</h2>
        <p>Downloads the current Eve identity/context bootstrap payload as JSON.</p>
        <a class="button" href="{html_escape(bootstrap_url)}">Download Bootstrap JSON</a>
      </div>
      <div class="card">
        <h2>Code Bundle</h2>
        <p>Downloads the current Eve application code bundle as a zip archive.</p>
        <a class="button secondary" href="{html_escape(code_url)}">Download Code Bundle</a>
      </div>
      <div class="card">
        <h2>App Package</h2>
        <p>Downloads the current Windows app payload bundle used by the updater for full app-file refreshes.</p>
        <a class="button" href="{html_escape(app_package_url)}">Download App Package</a>
      </div>
    </section>
    <section class="card" style="margin-top: 20px;">
      <h2>Quick Start</h2>
      <p>After downloading <code>EveSetup.exe</code> to the Windows machine, double-click it or run:</p>
      <pre>{html_escape(install_command)}</pre>
      <p>To pull later updates including code, download and run:</p>
      <pre>{html_escape(update_command)}</pre>
      <p>Advanced/manual downloads:</p>
      <p><a href="{html_escape(install_url)}">Installer launcher (.cmd)</a></p>
      <pre>{html_escape(advanced_install_command)}</pre>
      <pre>{html_escape(advanced_update_command)}</pre>
      <ul>
        <li><code>-PullModels</code> downloads the configured models into local Ollama on Windows.</li>
        <li><code>-UsePrimaryOllama</code> points the Windows machine at this Mac's Ollama host instead of downloading models locally.</li>
        <li><code>-IncludeCode</code> updates local Eve code files and stores backups under <code>.eve/code_update_backups/</code>.</li>
        <li><code>-IncludeApp</code> refreshes the installed Windows app payload with the external app-package helper.</li>
      </ul>
    </section>
  </main>
</body>
</html>
"""
    return html.encode("utf-8")


def render_install_page(base_url: str, primary_host: str, api_port: int) -> bytes:
    primary_host, api_port = trusted_installer_endpoint(primary_host, api_port)
    base_url = f"http://{eve_http_security.http_authority(primary_host, api_port)}"
    windows_url = f"{base_url}/downloads/EveSetup.exe"
    macos_url = f"{base_url}/downloads/{MAC_INSTALLER_FILENAME}"
    macos_script_url = f"{base_url}/downloads/EveMacSetup.zip"
    linux_url = f"{base_url}/downloads/EveLinuxSetup.tar.gz"
    windows_page_url = f"{base_url}/install/windows"
    html = f"""\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Eve Installer Downloads</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3ede2;
      --paper: rgba(255, 250, 242, 0.88);
      --paper-strong: #fffaf2;
      --ink: #191612;
      --muted: #6a6051;
      --line: rgba(81, 67, 50, 0.16);
      --accent: #0a6a58;
      --accent-strong: #084d40;
      --accent-soft: rgba(10, 106, 88, 0.12);
      --warm: #b85c31;
      --warm-soft: rgba(184, 92, 49, 0.12);
      --shadow: 0 24px 80px rgba(44, 27, 7, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Iowan Old Style", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 18%, rgba(10, 106, 88, 0.14), transparent 30%),
        radial-gradient(circle at 85% 12%, rgba(184, 92, 49, 0.16), transparent 28%),
        linear-gradient(180deg, #fbf6ed 0%, var(--bg) 58%, #ece3d4 100%);
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(25, 22, 18, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(25, 22, 18, 0.04) 1px, transparent 1px);
      background-size: 34px 34px;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.12), transparent 70%);
    }}
    main {{
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 72px;
      position: relative;
      z-index: 1;
    }}
    .masthead {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      margin-bottom: 20px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 250, 242, 0.72);
      backdrop-filter: blur(14px);
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }}
    .mark {{
      width: 42px;
      height: 42px;
      border-radius: 50%;
      display: grid;
      place-items: center;
      font-size: 18px;
      color: #fff;
      background:
        radial-gradient(circle at 30% 30%, #2dc39e, transparent 34%),
        linear-gradient(145deg, var(--accent), var(--accent-strong));
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.35);
    }}
    .brand h1 {{
      margin: 0;
      font-size: 1rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .brand p {{
      margin: 2px 0 0;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .host-pill {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border-radius: 999px;
      background: var(--paper-strong);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.94rem;
      white-space: nowrap;
    }}
    .status-dot {{
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 5px var(--accent-soft);
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      padding: 42px;
      min-height: 420px;
      border-radius: 32px;
      background:
        radial-gradient(circle at 78% 22%, rgba(255, 255, 255, 0.72), transparent 22%),
        radial-gradient(circle at 80% 80%, rgba(184, 92, 49, 0.20), transparent 26%),
        linear-gradient(140deg, rgba(10, 106, 88, 0.95), rgba(8, 77, 64, 0.95) 48%, rgba(20, 33, 30, 0.98));
      box-shadow: var(--shadow);
      color: #fff7ee;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -8% -28% auto;
      width: 380px;
      height: 380px;
      border-radius: 50%;
      background:
        radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.24), transparent 40%),
        radial-gradient(circle at 35% 35%, rgba(255, 214, 184, 0.52), transparent 30%);
      opacity: 0.95;
      filter: blur(6px);
    }}
    .hero-grid {{
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(290px, 0.8fr);
      gap: 28px;
      align-items: end;
    }}
    .eyebrow {{
      margin: 0 0 14px;
      color: rgba(255, 247, 238, 0.76);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.82rem;
    }}
    .hero h2 {{
      margin: 0;
      max-width: 10ch;
      font-size: clamp(2.8rem, 7vw, 5.8rem);
      line-height: 0.92;
      letter-spacing: -0.06em;
    }}
    .hero-copy {{
      max-width: 36rem;
      margin: 18px 0 0;
      font-size: 1.12rem;
      line-height: 1.6;
      color: rgba(255, 247, 238, 0.86);
    }}
    .hero-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 24px;
    }}
    a.button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 10px;
      min-height: 48px;
      padding: 0 18px;
      border-radius: 999px;
      border: 1px solid transparent;
      background: #fff7ee;
      color: var(--accent-strong);
      text-decoration: none;
      font-weight: 700;
      transition: transform 160ms ease, background 160ms ease, border-color 160ms ease;
    }}
    a.button:hover {{
      transform: translateY(-1px);
    }}
    a.button.secondary {{
      background: transparent;
      color: #fff7ee;
      border-color: rgba(255, 247, 238, 0.28);
    }}
    .hero-panel {{
      align-self: stretch;
      padding: 22px;
      border-radius: 24px;
      background: rgba(255, 250, 242, 0.10);
      border: 1px solid rgba(255, 247, 238, 0.14);
      backdrop-filter: blur(10px);
    }}
    .hero-panel h3 {{
      margin: 0 0 12px;
      font-size: 1rem;
      color: rgba(255, 247, 238, 0.74);
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}
    .hero-panel ul {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 12px;
    }}
    .hero-panel li {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid rgba(255, 247, 238, 0.14);
    }}
    .hero-panel li:last-child {{
      padding-bottom: 0;
      border-bottom: 0;
    }}
    .hero-panel strong {{
      display: block;
      font-size: 1rem;
      color: #fff7ee;
    }}
    .hero-panel span {{
      color: rgba(255, 247, 238, 0.68);
      font-size: 0.92rem;
    }}
    .hero-panel em {{
      font-style: normal;
      color: #ffd4bd;
      white-space: nowrap;
    }}
    .section-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 20px;
      align-items: end;
      margin: 34px 0 16px;
    }}
    .section-head h3 {{
      margin: 0;
      font-size: clamp(1.8rem, 4vw, 2.6rem);
      letter-spacing: -0.05em;
    }}
    .section-head p {{
      margin: 0;
      max-width: 34rem;
      color: var(--muted);
      line-height: 1.55;
    }}
    .platform-list {{
      display: grid;
      gap: 16px;
    }}
    .platform {{
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(220px, 0.9fr) auto;
      gap: 20px;
      align-items: center;
      padding: 24px;
      border: 1px solid var(--line);
      border-radius: 26px;
      background: var(--paper);
      backdrop-filter: blur(12px);
      box-shadow: 0 14px 42px rgba(44, 27, 7, 0.08);
    }}
    .platform.kicker-windows {{
      background:
        linear-gradient(0deg, rgba(255, 250, 242, 0.92), rgba(255, 250, 242, 0.92)),
        linear-gradient(90deg, rgba(10, 106, 88, 0.16), transparent 40%);
    }}
    .platform.kicker-macos {{
      background:
        linear-gradient(0deg, rgba(255, 250, 242, 0.92), rgba(255, 250, 242, 0.92)),
        linear-gradient(90deg, rgba(184, 92, 49, 0.14), transparent 40%);
    }}
    .platform.kicker-linux {{
      background:
        linear-gradient(0deg, rgba(255, 250, 242, 0.92), rgba(255, 250, 242, 0.92)),
        linear-gradient(90deg, rgba(37, 64, 138, 0.12), transparent 40%);
    }}
    .platform-tag {{
      display: inline-block;
      margin-bottom: 10px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.78rem;
    }}
    .platform h4 {{
      margin: 0 0 10px;
      font-size: 1.6rem;
      letter-spacing: -0.04em;
    }}
    .platform p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
    }}
    .platform ul {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 8px;
      color: var(--ink);
      font-size: 0.96rem;
    }}
    .platform li::before {{
      content: "•";
      color: var(--accent);
      margin-right: 10px;
    }}
    .platform-actions {{
      display: grid;
      justify-items: end;
      gap: 10px;
    }}
    .platform-actions a {{
      white-space: nowrap;
    }}
    .link-inline {{
      color: var(--accent-strong);
      text-decoration-color: rgba(8, 77, 64, 0.24);
      font-weight: 600;
    }}
    .network {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin-top: 18px;
    }}
    .network-item {{
      padding: 18px 20px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: rgba(255, 250, 242, 0.78);
    }}
    .network-item strong {{
      display: block;
      margin-bottom: 8px;
      font-size: 0.9rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }}
    .network-item code {{
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 0.96rem;
      word-break: break-word;
    }}
    .footnote {{
      margin-top: 12px;
      color: var(--muted);
      line-height: 1.55;
    }}
    @media (max-width: 900px) {{
      .masthead,
      .section-head,
      .platform,
      .hero-grid,
      .network {{
        grid-template-columns: 1fr;
      }}
      .masthead {{
        border-radius: 24px;
      }}
      .platform-actions {{
        justify-items: start;
      }}
      .host-pill {{
        white-space: normal;
      }}
    }}
    @media (max-width: 640px) {{
      main {{
        width: min(100% - 20px, 100%);
        padding-top: 12px;
      }}
      .hero {{
        padding: 28px 22px;
        min-height: 0;
      }}
      .hero h2 {{
        max-width: none;
      }}
      .platform {{
        padding: 20px;
      }}
      .network-item code {{
        font-size: 0.9rem;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="masthead">
      <div class="brand">
        <div class="mark">E</div>
        <div>
          <h1>Eve Installer</h1>
          <p>One page. Pick the machine. Download the right build.</p>
        </div>
      </div>
      <div class="host-pill">
        <span class="status-dot"></span>
        Serving from {html_escape(primary_host)}:{api_port}
      </div>
    </header>

    <section class="hero">
      <div class="hero-grid">
        <div>
          <p class="eyebrow">Cross-platform bootstrap</p>
          <h2>Bring Eve onto any system.</h2>
          <p class="hero-copy">Open this page from the target machine, choose its operating system, and download an installer that already knows how to connect back to this Mac.</p>
          <div class="hero-actions">
            <a class="button" href="{html_escape(windows_url)}">Windows Installer</a>
            <a class="button secondary" href="{html_escape(macos_url)}">macOS Installer</a>
          </div>
        </div>
        <aside class="hero-panel">
          <h3>What this page gives you</h3>
          <ul>
            <li>
              <div>
                <strong>Host-aware installers</strong>
                <span>Each download is already pointed at this Eve host.</span>
              </div>
              <em>Ready now</em>
            </li>
            <li>
              <div>
                <strong>Prototype-friendly setup</strong>
                <span>Good for testing on your Mac, a PC, or a Linux box on the same network.</span>
              </div>
              <em>LAN flow</em>
            </li>
            <li>
              <div>
                <strong>Direct access to deeper tools</strong>
                <span>Windows detail page, fallback script bundles, and raw update assets stay available.</span>
              </div>
              <em>No hunting</em>
            </li>
          </ul>
        </aside>
      </div>
    </section>

    <section>
      <div class="section-head">
        <div>
          <h3>Choose the target system</h3>
          <p>Each path is tuned for a different machine, but they all start from this same Eve host.</p>
        </div>
      </div>
      <div class="platform-list">
        <article class="platform kicker-windows">
          <div>
            <span class="platform-tag">Windows</span>
            <h4>Best for the PC prototype</h4>
            <p>Downloads the real Windows installer executable and sets up Eve to call back to this Mac for bootstrap, updates, and app refreshes.</p>
          </div>
          <ul>
            <li>One-click `EveSetup.exe` install flow</li>
            <li>Auto-update path for code and app payloads</li>
            <li>Dedicated detail page for advanced Windows tools</li>
          </ul>
          <div class="platform-actions">
            <a class="button" href="{html_escape(windows_url)}">Download EveSetup.exe</a>
            <a class="link-inline" href="{html_escape(windows_page_url)}">Open Windows detail page</a>
          </div>
        </article>

        <article class="platform kicker-macos">
          <div>
            <span class="platform-tag">macOS</span>
            <h4>Double-click installer app</h4>
            <p>Downloads the versioned macOS installer app bundle for another Mac, with a fallback script bundle available if Gatekeeper or app launch gets in the way.</p>
          </div>
          <ul>
            <li>Installer app is versioned to avoid stale cache confusion</li>
            <li>Falls back to the primary Ollama host when needed</li>
            <li>Script bundle still available for manual recovery</li>
          </ul>
          <div class="platform-actions">
            <a class="button" href="{html_escape(macos_url)}">Download {html_escape(MAC_INSTALLER_FILENAME)}</a>
            <a class="link-inline" href="{html_escape(macos_script_url)}">Get script bundle instead</a>
          </div>
        </article>

        <article class="platform kicker-linux">
          <div>
            <span class="platform-tag">Linux</span>
            <h4>Host-aware setup bundle</h4>
            <p>Downloads a Linux archive with an install script that bootstraps Eve against this machine, then switches into local services where available.</p>
          </div>
          <ul>
            <li>Good fit for a test box or sidecar node</li>
            <li>Native Linux bootstrap and local runtime layout</li>
            <li>Small, inspectable shell-based install path</li>
          </ul>
          <div class="platform-actions">
            <a class="button" href="{html_escape(linux_url)}">Download EveLinuxSetup.tar.gz</a>
          </div>
        </article>
      </div>
    </section>

    <section>
      <div class="section-head">
        <div>
          <h3>On this network</h3>
          <p>Use the direct address from the target machine. If hostname resolution is flaky, the raw LAN IP is the most direct route.</p>
        </div>
      </div>
      <div class="network">
        <div class="network-item">
          <strong>Install page</strong>
          <code>{html_escape(base_url)}/install</code>
        </div>
        <div class="network-item">
          <strong>Primary host</strong>
          <code>{html_escape(primary_host)}:{api_port}</code>
        </div>
        <div class="network-item">
          <strong>Mac installer version</strong>
          <code>{html_escape(MAC_INSTALLER_VERSION)}</code>
        </div>
      </div>
      <p class="footnote">Open this page on the machine you want to install to, not just on the primary Mac. That keeps the flow simple: download, run, and let Eve connect back here.</p>
    </section>
  </main>
</body>
</html>
"""
    return html.encode("utf-8")
