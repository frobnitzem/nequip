from typing import Union
import contextlib
import contextvars

import torch

import e3nn

_CONDITIONAL_TORCHSCRIPT_MODE = contextvars.ContextVar(
    "_CONDITIONAL_TORCHSCRIPT_MODE", default=True
)


@contextlib.contextmanager
def conditional_torchscript_mode(enabled: bool):
    global _CONDITIONAL_TORCHSCRIPT_MODE
    # save previous state
    init_val_e3nn = e3nn.get_optimization_defaults()["jit_script_fx"]
    init_val_here = _CONDITIONAL_TORCHSCRIPT_MODE.get()
    # set mode variables
    e3nn.set_optimization_defaults(jit_script_fx=enabled)
    _CONDITIONAL_TORCHSCRIPT_MODE.set(enabled)
    yield
    # restore state
    e3nn.set_optimization_defaults(jit_script_fx=init_val_e3nn)
    _CONDITIONAL_TORCHSCRIPT_MODE.set(init_val_here)


def conditional_torchscript_jit(
    module: torch.nn.Module,
) -> Union[torch.jit.ScriptModule, torch.nn.Module]:
    """Compile a module with TorchScript, conditional on whether it is enabled by ``conditional_torchscript_mode``"""
    global _CONDITIONAL_TORCHSCRIPT_MODE
    if _CONDITIONAL_TORCHSCRIPT_MODE.get():
        return torch.jit.script(module)
    else:
        return module
