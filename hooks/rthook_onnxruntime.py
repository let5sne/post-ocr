import os
import sys

# Ensure onnxruntime native DLLs are findable
if sys.platform == "win32" and hasattr(sys, "_MEIPASS"):
    capi_dir = os.path.join(sys._MEIPASS, "onnxruntime", "capi")
    if os.path.isdir(capi_dir):
        os.environ["PATH"] = capi_dir + os.pathsep + sys._MEIPASS + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(capi_dir)
            os.add_dll_directory(sys._MEIPASS)
        except (OSError, AttributeError):
            pass
