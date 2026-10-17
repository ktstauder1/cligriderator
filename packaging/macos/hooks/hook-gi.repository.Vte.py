"""Collect VTE 2.91's typelib, native library and introspection dependencies."""
from PyInstaller.utils.hooks.gi import GiModuleInfo


def hook(hook_api):
    module = GiModuleInfo("Vte", "2.91", hook_api=hook_api)
    if not module.available:
        raise RuntimeError("VTE 2.91 is required to build Cli Griderator")
    binaries, datas, imports = module.collect_typelib_data()
    hook_api.add_binaries(binaries)
    hook_api.add_datas(datas)
    hook_api.add_imports(*imports)
