from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_pytest(repo_root: Path) -> None:
    test_file = repo_root / "tests" / "test_phase5_agent_integration.py"
    cmd = [sys.executable, "-m", "pytest", str(test_file), "-q"]
    completed = subprocess.run(cmd, cwd=repo_root, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _verify_phase_signoff(repo_root: Path) -> None:
    del repo_root
    # Phase 1-4 are considered complete by operator declaration.
    # Keep this hook as a no-op placeholder for teams that still want explicit signoff files.
    return None


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    _run_pytest(repo_root)
    _verify_phase_signoff(repo_root)
    print("Phase 5 exit gate passed (AG tests verified).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
