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


def split_yum_groups(packages: list[str]) -> tuple[list[str], list[str]]:
    """Split yum requirements into 'groupinstall' and single packages."""
    single, groups = [], []
    for pkg in packages:
        if pkg.startswith("group:"):
            group = pkg.split(":", 1)[1]
            groups.append(group.strip("'").strip('"'))
        else:
            single.append(pkg)
    return single, groups


def get_yum_install_commands(packages: list[str], sudo: bool = True) -> list[list[str]]:
    """Get yum requirements installation commands."""
    singles, groups = split_yum_groups(packages)
    if not singles and not groups:
        return []

    commands = []
    prefix = ["sudo"] if sudo else []
    if groups:
        commands.append([*prefix, "yum", "-y", "groupinstall", *groups])
    if singles:
        commands.append([*prefix, "yum", "-y", "install", *singles])
    return commands


class PackageManager(enum.Enum):
    """Supported [system] package managers."""

    yum = enum.auto()
    apt = enum.auto()
    conda = enum.auto()
    brew = enum.auto()

    @property
    def requires_sudo(self) -> bool:
        return self in (PackageManager.apt, PackageManager.yum)

    def get_commands(
        self,
        packages: list[str],
        *,
        sudo: bool = False,
        conda_path: Optional[str] = None,
    ) -> list[list[str]]:
        if self == PackageManager.yum:
            return get_yum_install_commands(packages, sudo=sudo)

        prefix = ["sudo"] if sudo else []
        if self == PackageManager.conda:
            if conda_path is None:
                conda_path = find_conda_path()
            command = [*prefix, conda_path, "install", "-y"]
        elif self == PackageManager.apt:
            command = [*prefix, "apt-get", "install", "-y"]
        elif self == PackageManager.brew:
            command = [*prefix, "brew", "install"]
        else:
            raise NotImplementedError

        return [[*command, *packages]]


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


def get_install_commands(
    reqs: Requirements,
    source: PackageManager | str,
    sudo: bool = True,
    conda_path: Optional[str] = None,
) -> list[list[str]]:
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
    list[list[str]] or None
        List of commands to run, split by command-line arguments.
    """
    if not isinstance(source, PackageManager):
        source = PackageManager[source]

    source_reqs = getattr(reqs, source.name)
    if not source_reqs:
        return []

    return source.get_commands(
        conda_path=conda_path,
        sudo=source.requires_sudo and sudo,
        packages=source_reqs,
    )
