"""Small, dependency-free checks for tracked Markdown; see CONTRIBUTING.md."""

from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]\n]+\]\(([^\s)]+)\)")
CONFLICT = re.compile(r"^(?:<{7}|={7}|>{7})(?:\s|$)")


def main() -> int:
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "*.md"], cwd=ROOT
    ).decode("utf-8").split("\0")
    names = [name for name in tracked if name]
    errors = []
    if not names:
        errors.append("No tracked Markdown files found; stage new files first.")
    for name in names:
        path = ROOT / name
        try:
            raw = path.read_bytes()
            content = raw.decode("utf-8")
        except (OSError, UnicodeError) as error:
            errors.append(f"{name}: {error}")
            continue
        if not raw or not raw.endswith(b"\n"):
            errors.append(f"{name}: missing content or final newline")
        if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf"):
            errors.append(f"{name}: use UTF-8 without BOM and LF line endings")
        in_fence = False
        for number, line in enumerate(content.splitlines(), 1):
            prefix = f"{name}:{number}"
            if line.rstrip() != line:
                errors.append(f"{prefix}: trailing whitespace")
            if CONFLICT.match(line):
                errors.append(f"{prefix}: possible merge conflict marker")
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for target in LINK.findall(line):
                parsed = urlsplit(target.strip("<>"))
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                destination = (path.parent / unquote(parsed.path)).resolve()
                if not destination.is_relative_to(ROOT) or not destination.exists():
                    errors.append(f"{prefix}: missing or external local target: {target}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Documentation checks passed for {len(names)} Markdown files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
