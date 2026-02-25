#!/usr/bin/env python3
"""
Windows packaging script (RapidOCR only).
Usage: python build_win.py [--debug]

Output: dist/信封信息提取系统/
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_NAME = "信封信息提取系统"


def _find_package_dir(pkg_name: str) -> Path:
    """Locate installed package directory via pip show."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", pkg_name.replace("_", "-")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Try with underscores too
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", pkg_name],
            capture_output=True, text=True,
        )
    if result.returncode != 0:
        raise FileNotFoundError(f"Package not installed: {pkg_name}")
    for line in result.stdout.splitlines():
        if line.startswith("Location:"):
            location = Path(line.split(":", 1)[1].strip())
            pkg_dir = location / pkg_name
            if pkg_dir.is_dir():
                return pkg_dir
    raise FileNotFoundError(f"Cannot locate package directory for {pkg_name}")


def build(debug=False):
    print("Packaging (Windows + RapidOCR) ...")
    print(f"Working dir: {PROJECT_ROOT}")
    print(f"Mode: {'debug' if debug else 'release'}")
    print("-" * 50)

    rapid_dir = _find_package_dir("rapidocr_onnxruntime")
    onnx_dir = _find_package_dir("onnxruntime")
    print(f"rapidocr_onnxruntime: {rapid_dir}")
    print(f"onnxruntime: {onnx_dir}")

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        f"--name={DIST_NAME}",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--paths=src",
        "--additional-hooks-dir=hooks",
        "--runtime-hook=hooks/rthook_onnxruntime.py",
        # --- hidden imports ---
        "--hidden-import=cv2",
        "--hidden-import=PIL",
        "--hidden-import=processor",
        "--hidden-import=ocr_engine",
        "--hidden-import=ocr_worker_process",
        "--hidden-import=rapidocr_onnxruntime",
        # --- add packages directly from venv ---
        f"--add-data={rapid_dir}{os.pathsep}rapidocr_onnxruntime",
        f"--add-data={onnx_dir}{os.pathsep}onnxruntime",
        f"--add-binary={onnx_dir / 'capi' / '*.dll'}{os.pathsep}onnxruntime/capi",
        f"--add-binary={onnx_dir / 'capi' / '*.pyd'}{os.pathsep}onnxruntime/capi",
    ]

    if not debug:
        cmd.append("--windowed")
    else:
        cmd.append("--console")

    cmd.append("src/desktop.py")

    try:
        subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("PyInstaller not found. pip install pyinstaller")
        sys.exit(1)

    dist_dir = PROJECT_ROOT / "dist" / DIST_NAME
    if not (dist_dir / f"{DIST_NAME}.exe").exists():
        print("Warning: output exe not found")
        return

    # Post-build: copy onnxruntime native DLLs to _internal/ root
    # so they are on the default DLL search path for subprocesses
    capi_dir = dist_dir / "_internal" / "onnxruntime" / "capi"
    internal_dir = dist_dir / "_internal"
    if capi_dir.is_dir():
        for dll in capi_dir.glob("*.dll"):
            dst = internal_dir / dll.name
            if not dst.exists():
                shutil.copy2(dll, dst)
                print(f"  Copied {dll.name} -> _internal/")

    size = sum(
        f.stat().st_size for f in dist_dir.rglob("*") if f.is_file()
    ) / 1024 / 1024
    print(f"\nDone! Output: {dist_dir}  ({size:.1f} MB)")


if __name__ == "__main__":
    build(debug="--debug" in sys.argv)
