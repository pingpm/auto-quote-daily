"""Install the skill's allowlisted resources without copying data or credentials."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills"
    parser.add_argument("--skills-dir", type=Path, default=default_root)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    destination = args.skills_dir.expanduser().resolve() / "auto-quote-daily"
    if destination.exists():
        parser.error(f"Skill already exists: {destination}. Choose another skills directory or review the existing installation first.")
    destination.mkdir(parents=True)
    for name in ("SKILL.md", "AGENTS.md", "README.md", "pyproject.toml", "MANIFEST.in"):
        shutil.copy2(source / name, destination / name)
    shutil.copytree(source / "references", destination / "references")
    shutil.copytree(source / "scripts" / "auto_quote_daily", destination / "scripts" / "auto_quote_daily",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(source / "scripts" / "install_skill.py", destination / "scripts" / "install_skill.py")
    print(f"Installed skill: {destination}")
    print(f'Install runtime in your Python environment: python -m pip install "{destination}"')
    print("Restart the agent session to discover the new skill.")


if __name__ == "__main__":
    main()
