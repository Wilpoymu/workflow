"""Install frontend dependencies using bun."""
import subprocess
import sys
from pathlib import Path


def main():
    # --detect flag: just print PM name (for build-ext.bat)
    if len(sys.argv) > 1 and sys.argv[1] == "--detect":
        print("bun")
        return True

    frontend_dir = Path(__file__).parent.parent / "frontend"

    node_modules = frontend_dir / "node_modules"
    if node_modules.is_dir():
        print("[FRONTEND] Dependencies already installed.")
        return True

    print("[FRONTEND] Installing dependencies...")
    try:
        subprocess.run(["bun", "install"], cwd=frontend_dir, check=True, timeout=120)
        print("[FRONTEND] Installation complete.")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"[ERROR] Install failed: {e}")
        return False


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
