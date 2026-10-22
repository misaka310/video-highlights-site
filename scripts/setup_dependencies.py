from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def npm_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["npm_config_cache"] = str(ROOT / ".cache" / "npm")
    if os.name == "nt":
        system_root = environment.get("SystemRoot") or r"C:\Windows"
        environment.setdefault("COMSPEC", str(Path(system_root) / "System32" / "cmd.exe"))
        environment.setdefault("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return environment


def run_npm_ci(directory: Path) -> None:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required; install a supported, security-patched Node.js LTS (22.23.4 or 24.22.1)")
    print(f"+ {npm} ci (cwd={directory})", flush=True)
    subprocess.run([npm, "ci"], cwd=directory, check=True, env=npm_environment())


def main() -> int:
    try:
        run_npm_ci(ROOT)
        run_npm_ci(FRONTEND)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"dependency setup failed: {exc}", file=sys.stderr)
        return 1
    print("dependency setup passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
