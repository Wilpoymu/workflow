"""Validate that all backend dependencies are installed before starting."""
import importlib
import sys
from pathlib import Path


def check(package: str, import_name: str | None = None, min_version: str | None = None) -> bool:
    name = import_name or package
    try:
        mod = importlib.import_module(name)
        if min_version:
            ver = getattr(mod, "__version__", "0")
            if ver < min_version:
                print(f"  ✗ {package}: installed {ver}, need >= {min_version}")
                return False
        print(f"  ✓ {package}")
        return True
    except ImportError:
        print(f"  ✗ {package}: NOT INSTALLED")
        return False


def main():
    print()
    print("=" * 50)
    print("  Workflow — Backend Dependency Check")
    print("=" * 50)
    print()
    print(f"  Python: {sys.version.split()[0]}")
    print()

    # Read requirements
    req_path = Path(__file__).parent / "requirements.txt"
    if not req_path.exists():
        print("  ✗ requirements.txt not found!")
        return False

    required = [
        ("fastapi",),
        ("uvicorn",),
        ("pydantic",),
        ("pydantic-settings", "pydantic_settings"),
        ("python-multipart", "multipart"),
        ("websockets",),
        ("aiofiles",),
        ("aiosqlite",),
        ("faster-whisper", "faster_whisper"),
        ("ctranslate2",),
        ("Pillow", "PIL"),
        ("PyYAML", "yaml"),
        ("httpx",),
        ("curl-cffi", "curl_cffi"),
    ]

    all_ok = True
    for pkg in required:
        name = pkg[0]
        import_name = pkg[1] if len(pkg) > 1 else None
        if not check(name, import_name):
            all_ok = False

    print()
    if all_ok:
        print("  ✅ All dependencies satisfied!")
    else:
        print("  ❌ Some dependencies are missing.")
        print()
        print("  Install them with:")
        print(f"    pip install -r {req_path}")
        print()

    return all_ok


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
