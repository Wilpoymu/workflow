"""Detect package manager and install frontend dependencies."""
import subprocess
import sys
from pathlib import Path


def detect_pm() -> str:
    """Detect available package manager: bun > npm."""
    for pm in ["bun", "npm"]:
        try:
            subprocess.run(
                [pm, "--version"],
                capture_output=True, timeout=10, check=True,
            )
            return pm
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    return ""


def main():
    frontend_dir = Path(__file__).parent.parent / "frontend"

    # --detect flag: just print PM name and exit (for build-ext.bat)
    if len(sys.argv) > 1 and sys.argv[1] == "--detect":
        pm = detect_pm()
        print(pm)
        return pm != ""

    pm = detect_pm()
    if not pm:
        print("[FRONTEND] No package manager found.")
        print("  Install Node.js from https://nodejs.org")
        return False

    print(f"[FRONTEND] Using {pm}")

    node_modules = frontend_dir / "node_modules"
    if node_modules.is_dir():
        print("[FRONTEND] Dependencies already installed.")
        return True

    print("[FRONTEND] Installing dependencies...")
    try:
        subprocess.run([pm, "install"], cwd=frontend_dir, check=True, timeout=120)
        print("[FRONTEND] Installation complete.")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[ERROR] Install failed: {e}")
        return False


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
