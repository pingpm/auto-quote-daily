"""Build a source installation ZIP from explicit package resources."""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "dist"
    output.mkdir(exist_ok=True)
    files = [root / name for name in ("SKILL.md", "AGENTS.md", "README.md", "pyproject.toml", "MANIFEST.in", ".gitignore")]
    for directory, suffix in (("references", ".md"), ("scripts", ".py"), ("tests", ".py")):
        files.extend(path for path in (root / directory).rglob(f"*{suffix}") if "__pycache__" not in path.parts)
    archive = output / "auto-quote-daily-1.0.0.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(files):
            content = path.read_bytes()
            handle.writestr(f"auto-quote-daily/{path.relative_to(root).as_posix()}", content)
    artifacts = [archive, *sorted(output.glob("*.whl")), *sorted(output.glob("*.tar.gz"))]
    (output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts
    ), encoding="ascii")
    print(f"Built {archive} ({len(files)} allowlisted source files)")


if __name__ == "__main__":
    main()
