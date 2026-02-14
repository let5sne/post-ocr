"""
PyInstaller runtime hook: stub 掉 paddle 中仅开发时需要的模块，
避免打包后因缺少 Cython Utility 文件而崩溃。
"""
import types
import sys


class _Stub(types.ModuleType):
    """空模块 stub，所有属性访问返回空类"""
    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return type(name, (), {})


def _inject(name):
    if name not in sys.modules:
        m = _Stub(name)
        m.__path__ = []
        m.__package__ = name
        m.__spec__ = None
        sys.modules[name] = m


# paddle.utils.cpp_extension 会拉入 Cython 编译器，推理不需要
for _p in [
    "paddle.utils.cpp_extension",
    "paddle.utils.cpp_extension.cpp_extension",
    "paddle.utils.cpp_extension.extension_utils",
    "paddle.utils.cpp_extension.jit_compile",
]:
    _inject(_p)
