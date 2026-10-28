"""Opt-in lean child caps; excluded from the shipped, reviewed helper recipe.

A lean helper must be separately packaged and reviewed before activation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from ac_platform.conversation_intelligence.native_runtime import (
    DockerNativeRuntime,
    NativeRuntimeError,
)


class LeanDockerNativeRuntime(DockerNativeRuntime):
    def __init__(
        self,
        image_ref: str,
        *,
        memory_mib: int = 192,
        cgroup_parent: str = "native.slice",
        **kwargs: Any,
    ) -> None:
        if (
            type(memory_mib) is not int
            or not 128 <= memory_mib <= 2048
            or not isinstance(cgroup_parent, str)
            or re.fullmatch(r"[A-Za-z0-9_.-]+\.slice", cgroup_parent) is None
        ):
            raise NativeRuntimeError("native_runtime_configuration_invalid")
        super().__init__(image_ref, **kwargs)
        self.memory_mib = memory_mib
        self.cgroup_parent = cgroup_parent

    def _command(
        self,
        source: Path,
        staging: Path,
        container_name: str,
        *,
        operation: Literal["inspect", "validate"],
    ) -> tuple[str, ...]:
        command = super()._command(source, staging, container_name, operation=operation)
        replacements = {
            "--memory=2g": f"--memory={self.memory_mib}m",
            "--memory-swap=2g": f"--memory-swap={self.memory_mib}m",
        }
        # Insert Docker options before the image, retaining all sandbox arguments.
        capped = tuple(replacements.get(argument, argument) for argument in command)
        index = capped.index("--cpus=1")
        return (
            *capped[:index],
            f"--cgroup-parent={self.cgroup_parent}",
            "--oom-score-adj=500",
            *capped[index:],
        )
