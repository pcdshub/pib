from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from whatrecord.makefile import Dependency, DependencyGroup, Makefile

from . import config, git, util
from .exceptions import DownloadFailureError, TargetDirectoryAlreadyExistsError
from .makefile import get_makefile_for_path
from .spec import GitSource, Module

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Generator
    try:
        from typing import Self
    except ImportError:
        from typing_extensions import Self
    from .config import Settings


logger = logging.getLogger(__name__)


@dataclass
class VersionInfo:
    """Module name and version information."""

    #: The name (i.e., repository name) of the module.
    name: str
    #: The version of EPICS base it is associated with.
    base: str
    #: The version tag name.
    tag: str

    # @property
    # def path(self) -> pathlib.Path:
    #     if self.name == "epics-base":
    #         return EPICS_SITE_TOP / "base" / self.tag
    #     return EPICS_SITE_TOP / self.tag / "modules"

    def to_module(self, variable_name: str, settings: Settings) -> Module:
        """
        Create a specification file ``Module`` out of this version.

        Parameters
        ----------
        variable_name : str
            The variable name to use.
        settings : Settings
            pib path convention settings.

        Returns
        -------
        Module
        """
        return Module(
            name=self.name,
            variable=variable_name,
            # install_path=self.path,
            git=GitSource(
                url=settings.site.get_git_url_for_version(self),
                tag=self.tag,
            ),
        )

    @classmethod
    def from_path(
        cls: type[Self],
        path: pathlib.Path,
        settings: Settings,
    ) -> Optional[Self]:
        """
        Create a VersionInfo instance from a given path.

        This uses the path conventions defined in the site settings to
        determine the base version, module version, and module name.

        Parameters
        ----------
        path : pathlib.Path
            The path to the module (or epics-base).
        settings : Settings
            pib settings that specify path conventions.

        Returns
        -------
        VersionInfo or None
            If the path does not match any configured conventions, ``None``
            will be returned.
        """
        path_str = str(settings.site.normalize_path(path))
        for regex in settings.site.module_path_regexes:
            match = re.match(regex, path_str)
            if match is not None:
                logger.debug("Module version path match %s -> %s", path_str, match.groupdict())
                return cls(**match.groupdict())
        for regex in settings.site.base_path_regexes:
            match = re.match(regex, path_str)
            if match is not None:
                logger.debug("Base version path match %s -> %s", path_str, match.groupdict())
                group = match.groupdict()
                return cls(name="epics-base", base=group["tag"], tag=group["tag"])
        return None

    # @property
    # def base_url(self) -> str:
    #     try:
    #         slac_tag = self.base.split("-")[1]
    #         looks_like_a_branch = slac_tag.count(".") <= 1
    #     except (ValueError, IndexError):
    #         looks_like_a_branch = False
    #
    #     if looks_like_a_branch:
    #         base = self.base.rstrip("0.")
    #         return f"https://github.com/slac-epics/epics-base/tree/{base}.branch"
    #     return f"https://github.com/slac-epics/epics-base/releases/tag/{self.base}"

    # @property
    # def url(self) -> str:
    #     return f"https://github.com/slac-epics/{self.name}/releases/tag/{self.tag}"


@dataclass
class MissingDependency:
    """Missing dependency information."""

    variable: str
    path: pathlib.Path
    version: Optional[VersionInfo]


def get_build_order(
    dependencies: list[Dependency],
    settings: Settings,
    build_first: Optional[list[str]] = None,
    skip: Optional[list[str]] = None,
) -> list[str]:
    """
    Get the build order by name.

    Parameters
    ----------
    dependencies : list[Dependency]
    settings : Settings
    build_first : list[str], optional
        Build these prior to other modules.
    skip : Optional[list[str]]
        Skip building these entirely.

    Returns
    -------
    list of str
        List of dependency names, in order of how they should be built.
    """
    # TODO: order based on dependency graph could/should be done efficiently
    skip = list(skip or [])
    build_order = list(build_first or ["epics-base"])
    name_to_dependency = {dep.name: dep for dep in dependencies}
    variable_name_to_dep = {dep.variable_name: dep for dep in dependencies}
    remaining = set(name_to_dependency) - set(build_order) - set(skip)
    last_remaining = None
    sub_deps = {
        dep.name: sorted(
            VersionInfo.from_path(subdep, settings=settings).name   # TODO
            for subdep in dep.dependencies.values()
        )
        for dep in dependencies
    }
    remaining_requires = {
        dep: [
            variable_name_to_dep[var].name
            for var in name_to_dependency[dep].dependencies
            if var != dep
        ]
        for dep in remaining
    }
    logger.debug(
        "Trying to determine build order based on these requirements: %s",
        remaining_requires,
    )
    while remaining:
        for to_check_name in sorted(remaining):
            dep = name_to_dependency[to_check_name]
            if all(subdep in build_order for subdep in sub_deps[dep.name]):
                build_order.append(to_check_name)
                remaining.remove(to_check_name)
        if last_remaining == remaining:
            remaining_requires = {
                dep: list(sub_deps[dep])
                for dep in remaining
            }
            logger.warning(
                f"Unable to determine build order.  Determined build order:\n"
                f"{build_order}\n"
                f"\n"
                f"Remaining:\n"
                f"{remaining}\n"
                f"\n"
                f"which require:\n"
                f"{remaining_requires}",
            )
            for remaining_dep in remaining:
                build_order.append(remaining_dep)
            break

        last_remaining = set(remaining)

    logger.debug("Determined build order: %s", ", ".join(build_order))
    return build_order


def get_makefile_for_module(module: Module, settings: config.Settings) -> Makefile:
    """
    Get a whatrecord Makefile instance for the provided module spec.

    Parameters
    ----------
    module : Module
        The module specification.
    settings : config.Settings
        Path and related settings.

    Returns
    -------
    Makefile
    """
    path = settings.get_path_for_module(module)
    return get_makefile_for_path(path, epics_base=settings.epics_base)


def get_dependency_group_for_module(
    module: Module,
    settings: config.Settings,
    *,
    recurse: bool = True,
    name: Optional[str] = None,
    variable_name: Optional[str] = None,
    keep_os_env: bool = False,
) -> DependencyGroup:
    """
    Get a whatrecord DependencyGroup for the specified module.

    Parameters
    ----------
    module : Module
        The module to check.
    settings : config.Settings
        Configuration settings regarding paths and such
    recurse : bool
        Recurse into dependencies, defaults to True.
    name : str, optional
        The name of the provided module, if not already set.
    variable_name : Optional[str]
        The variable name of the module, if not already set.
    keep_os_env : bool
        Keep OS environment variables after the introspection phase in
        the DependencyGroup metadata.

    Returns
    -------
    DependencyGroup
    """
    makefile = get_makefile_for_module(module, settings)
    res = DependencyGroup.from_makefile(
        makefile,
        recurse=recurse,
        variable_name=variable_name or module.variable,
        name=name or module.name,
        keep_os_env=keep_os_env,
    )
    for mod in res.all_modules.values():
        version = VersionInfo.from_path(mod.path, settings=settings)
        if version is None:
            raise ValueError(
                f"Dependency is not in a recognized path; version unknown. "
                f"{mod.name}: {mod.path}",
            )
        mod.name = version.name
    return res


def download_module(
    module: Module,
    settings: config.Settings,
    exist_ok: bool = False,
) -> pathlib.Path:
    path = settings.get_path_for_module(module)

    if path.exists():
        if not path.is_dir():
            raise RuntimeError(f"File exists where module should go: {path}")
        if not exist_ok:
            ex = TargetDirectoryAlreadyExistsError(f"Directories must be empty prior to the download step: {path}")
            ex.path = path
            raise ex

        # raise NotImplementedError("Checking / updating existing download (TODO)?")
        return path

    if module.git is None:
        raise NotImplementedError("only git-backed modules supported at the moment")

    logger.info("Downloading module %s to %s", module.name, path)
    if git.clone(
        module.git.url,
        branch_or_tag=module.version,  # or module.git.tag?
        to_path=path,
        depth=module.git.depth,
        recursive=module.git.recursive,
        args=shlex.split(module.git.args or ""),
        insert_template=settings.site.git_template,
    ):
        raise DownloadFailureError(
            f"Failed to download {module.git.url}; git returned a non-zero exit code",
        )

    return path


def find_missing_dependencies(
    dep: Dependency,
    settings: Settings,
) -> Generator[MissingDependency, None, None]:
    """
    Find all missing dependencies using module path conventions.

    ``missing_paths`` is allowed to be mutated during iteration.

    See Also
    --------
    :func:`VersionInfo.from_path`
    """
    for var, path in list(dep.missing_paths.items()):
        logger.debug("Checking missing path: %s", path)
        version_info = VersionInfo.from_path(path, settings=settings)
        missing = MissingDependency(
            variable=var,
            path=path,
            version=version_info,
        )
        if version_info is None:
            logger.debug("Dependency path for %s=%s does not match known patterns", var, path)
        else:
            logger.debug("Missing path matches version information: %s", version_info)
        yield missing


def guess_if_built(path: pathlib.Path) -> bool:
    """Guess if the module located in ``path`` has already been built."""
    host_arch = util.get_host_arch()
    lib_path = path / "lib" / host_arch
    if any(len(list(lib_path.glob(ext))) > 0 for ext in ("*.so*", "*.a", "*.dylib")):
        return True

    # bin_path = path / "bin" / host_arch
    return False
