"""Locate telemetry beside the running Windows simulator."""
from pathlib import Path
import subprocess
import sys


def running_simulator_folders():
    if sys.platform != "win32":
        return []
    command = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
               "Get-Process -Name 'ONR Scuba' -ErrorAction SilentlyContinue | "
               "Select-Object -ExpandProperty Path")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, text=True, encoding="utf-8-sig", timeout=5,
                                creationflags=0x08000000)
    except (OSError, subprocess.TimeoutExpired):
        return []
    folders = {Path(line.strip()).parent for line in result.stdout.splitlines()
               if Path(line.strip()).name.lower() == "onr scuba.exe"}
    return sorted(folders)


def simulator_folder(configured, override=None, state_file=None):
    if override:
        return Path(override).expanduser().resolve(), "--sim-dir"
    if state_file:
        return Path(configured).resolve(), "--state-file"
    folders = running_simulator_folders()
    if len(folders) == 1:
        return folders[0], "running simulator"
    configured = Path(configured).resolve()
    if len(folders) > 1:
        if configured in folders:
            return configured, "configured running simulator"
        raise ValueError("More than one simulator folder is running; select it with --sim-dir")
    return configured, "config"
