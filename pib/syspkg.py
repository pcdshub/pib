"""OS/package manager requirements / dependencies."""

import enum
import shutil
from typing import Optional

import apischema

from pib import exceptions

from .spec import Requirements


def find_conda_path() -> str:
    """Find the mamba or conda executable from the path."""
    for executable in ("micromamba", "mamba", "conda"):
        path = shutil.which(executable)
        if path is not None:
            return path

    raise exceptions.ProgramMissingError("Unable to find mamba/conda in the path")


class PackageManager(enum.Enum):
    """Supported [system] package managers."""

    yum = enum.auto()
    apt = enum.auto()
    conda = enum.auto()
    brew = enum.auto()

    @property
    def requires_sudo(self) -> bool:
        return self in (PackageManager.apt, PackageManager.yum)

    def get_command(
        self,
        sudo: bool = False,
        conda_path: Optional[str] = None,
    ) -> list[str]:
        if self == PackageManager.conda:
            if conda_path is None:
                conda_path = find_conda_path()
            command = [conda_path, "install", "-y"]
        elif self == PackageManager.yum:
            command = ["yum", "-y", "install"]
            # TODO: groupinstall support?
        elif self == PackageManager.apt:
            command = ["apt-get", "install", "-y"]
        elif self == PackageManager.brew:
            command = ["brew", "install"]
        else:
            raise NotImplementedError

        if sudo:
            return ["sudo", *command]
        return command


def guess_package_manager() -> PackageManager:
    """
    Guess the system package manager - yum or apt.

    Returns
    -------
    PackageManager

    Raises
    ------
    NotImplementedError
        If no supported package manager is found.
    """
    if shutil.which("yum"):
        return PackageManager.yum
    if shutil.which("apt-get"):
        return PackageManager.apt
    if shutil.which("brew"):
        return PackageManager.brew
    raise NotImplementedError("No supported OS package manager found")


def requirements_to_dict(reqs: Requirements) -> dict[str, list[str]]:
    """Convert requirements information to a dictionary for serialization."""
    return apischema.serialize(Requirements, reqs)


def get_install_command(
    reqs: Requirements,
    source: PackageManager | str,
    sudo: bool = True,
    conda_path: Optional[str] = None,
) -> Optional[list[str]]:
    """
    Get the command to run to install package requirements using the package manager.

    Parameters
    ----------
    reqs : Requirements
        The top-level requirements.
    source : PackageManager | str
        The specific package manager to use.
    sudo : bool
        Use sudo, if typically required.
    conda_path : Optional[str]
        Override the auto-detected conda path.

    Returns
    -------
    list[str] or None
        List of command-line arguments to run, or None if there are no
        dependencies to install.
    """
    if not isinstance(source, PackageManager):
        source = PackageManager[source]

    source_reqs = getattr(reqs, source.name)
    if not source_reqs:
        return None

    command = source.get_command(
        conda_path=conda_path,
        sudo=source.requires_sudo and sudo,
    )
    command.extend(source_reqs)
    return command
