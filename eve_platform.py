#!/usr/bin/env python3

import os
import shutil
import sys
from pathlib import Path
from typing import Dict


def current_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def is_macos() -> bool:
    return current_platform() == "macos"


def is_windows() -> bool:
    return current_platform() == "windows"


def is_linux() -> bool:
    return current_platform() == "linux"


def python_executable() -> str:
    current = str(sys.executable or "").strip()
    if current:
        return current
    discovered = shutil.which("python3") or shutil.which("python")
    return discovered or "python3"


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def notifications_supported() -> bool:
    return is_macos() or (is_linux() and command_available("notify-send"))


def battery_status_supported() -> bool:
    return is_macos() or (is_linux() and (Path("/sys/class/power_supply").exists() or command_available("upower")))


def runtime_dir() -> Path:
    override = os.environ.get("EVE_RUNTIME_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if is_macos():
        return Path.home() / ".eve_runtime"
    if is_windows():
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "Eve" / "runtime"
        return Path.home() / "AppData" / "Local" / "Eve" / "runtime"
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    if state_home:
        return Path(state_home) / "eve" / "runtime"
    return Path.home() / ".local" / "state" / "eve" / "runtime"


def service_manager() -> str:
    if is_macos():
        return "launchd"
    if is_linux() and command_available("systemctl"):
        return "systemd"
    if is_linux():
        return "linux-supervisor"
    if is_windows() and command_available("schtasks"):
        return "task_scheduler"
    if is_windows():
        return "windows-supervisor"
    return "none"


def service_definition_dir() -> Path:
    if is_macos():
        return Path.home() / "Library" / "LaunchAgents"
    if is_linux():
        config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if config_home:
            return Path(config_home) / "systemd" / "user"
        return Path.home() / ".config" / "systemd" / "user"
    if is_windows():
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Eve" / "services"
        return Path.home() / "AppData" / "Roaming" / "Eve" / "services"
    return runtime_dir() / "services"


def service_definition_path(label: str) -> Path:
    suffix = ".plist" if is_macos() else ".service" if is_linux() else ".xml"
    return service_definition_dir() / f"{label}{suffix}"


def service_timer_definition_path(label: str) -> Path:
    if is_linux():
        return service_definition_dir() / f"{label}.timer"
    return service_definition_path(label)


def native_service_install_supported() -> bool:
    return is_macos() or (is_linux() and command_available("systemctl")) or (is_windows() and command_available("schtasks"))


def daemon_native_service_supported() -> bool:
    return native_service_install_supported()


def watchdog_native_service_supported() -> bool:
    return native_service_install_supported()


def model_warm_native_service_supported() -> bool:
    return is_macos()


def platform_capabilities() -> Dict[str, object]:
    return {
        "platform": current_platform(),
        "service_manager": service_manager(),
        "native_service_install": native_service_install_supported(),
        "daemon_service_install": daemon_native_service_supported(),
        "watchdog_service_install": watchdog_native_service_supported(),
        "model_warm_service_install": model_warm_native_service_supported(),
        "notifications": notifications_supported(),
        "frontmost_app": is_macos(),
        "idle_tracking": is_macos(),
        "battery_status": battery_status_supported(),
        "native_mac_ui": is_macos(),
        "ollama_cli": command_available("ollama"),
        "rust_toolchain": command_available("cargo") and command_available("rustc"),
        "systemctl": command_available("systemctl"),
        "schtasks": command_available("schtasks"),
    }
