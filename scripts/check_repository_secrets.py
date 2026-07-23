from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ENV_FILES = {".env.example", "frontend/.env.example"}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[oprsu]_[A-Za-z0-9_]{20,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def main() -> int:
    violations: list[str] = []
    for relative_path in tracked_files():
        normalized = relative_path.replace("\\", "/")
        name = Path(normalized).name
        if name == ".env" or (name.startswith(".env.") and normalized not in ALLOWED_ENV_FILES):
            violations.append(f"tracked environment file: {normalized}")
            continue
        path = ROOT / relative_path
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                violations.append(f"{label} pattern in {normalized}")

    if violations:
        print("Repository secret policy failed:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    print("Repository secret policy passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
