from __future__ import annotations

import logging
import pathlib
import re
import shlex
import subprocess
import sys
import threading
import typing
from dataclasses import dataclass, field
from typing import Any, Optional, TextIO

from whatrecord.makefile import Makefile

from . import util

if typing.TYPE_CHECKING:
    import datetime
    from collections.abc import Generator


logger = logging.getLogger(__name__)


@dataclass
class MakeResult:
    """Result of a GNU make run."""

    command: str
    arguments: list[str]
    log: str
    exit_code: int
    start_dt: datetime.datetime = field(
        default_factory=util.dt_now,
    )
    finish_dt: datetime.datetime = field(
        default_factory=util.dt_now,
    )


def _start_timeout_thread(child: subprocess.Popen, timeout: float) -> threading.Timer:

    def expire(child: subprocess.Popen) -> None:
        logger.error("Timeout when running make")
        child.terminate()

    timer = threading.Timer(timeout, expire, args=(child,))
    timer.start()
    return timer


def call_make(
    args: list[str],
    path: Optional[pathlib.Path] = None,
    *,
    timeout: Optional[float] = None,
    parallel: int = 1,
    silent: bool = False,
    is_make3: bool = False,
    output_fd: Optional[TextIO] = sys.stdout,
    **popen_kwargs,  # noqa: ANN003
) -> MakeResult:
    """Run GNU make."""
    if path is None:
        path = pathlib.Path.cwd()

    if parallel <= 1:
        makeargs = []
    else:
        makeargs = [f"-j{parallel}"]
        if not is_make3:
            makeargs += ["-Otarget"]
    if silent:
        makeargs += ["-s"]

    command = ["make", *makeargs, *args]
    logger.debug("Running '%s' in %s", shlex.join(command), path)
    start_dt = util.dt_now()

    child = subprocess.Popen(
        command,  # noqa: S603
        cwd=path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **popen_kwargs,
    )

    timer = None
    if timeout is not None:
        timer = _start_timeout_thread(child, timeout)

    stdout: str = child.communicate()[0]
    code = child.wait()

    if output_fd is not None:
        print(stdout, file=output_fd)

    if timer is not None:
        timer.cancel()
    if code == 0:
        logger.debug("Ran %s successfully", shlex.join(command))
    else:
        logger.error("Ran %s unsuccessfully (code %d)", shlex.join(command), code)

    return MakeResult(
        command=shlex.join(command),
        arguments=makeargs + args,
        log=stdout,
        exit_code=code,
        start_dt=start_dt,
    )


def get_makefile_for_path(
    path: pathlib.Path,
    epics_base: pathlib.Path,
    variables: Optional[dict[str, str]] = None,
) -> Makefile:
    """
    Get a whatrecord :class:`Makefile` for the provided path.

    Parameters
    ----------
    path : pathlib.Path
        The path to search for a Makefile, or a path to the makefile
        itself.

    Returns
    -------
    Makefile
    """
    variables = dict(variables or {})
    variables["EPICS_BASE"] = str(epics_base)
    variables["_DEPENDENCY_CHECK_"] = "1"
    return Makefile.from_file(
        Makefile.find_makefile(path),
        keep_os_env=False,
        variables=variables,
    )


def patch_makefile_contents(
    contents: str,
    variables: dict[str, Any],
    *,
    filename: Optional[pathlib.Path | str] = None,
) -> tuple[list[str], set[str], set[str]]:
    """
    Patch Makefile variable declarations with those provided in ``variables``.

    Parameters
    ----------
    contents : str
        The contents of the Makefile.
    variables : Dict[str, Any]
        Variable-to-value dictionary.

    Returns
    -------
    str
        The new contents of the Makefile.
    Set[str]
        Set of variables encountered.
    Set[str]
        Set of updated variables.
    """
    updated = set()
    seen = set()
    # update_lines = {}

    def fix_line(line: str) -> str:
        if not line:
            return line
        if line[0] in " \t#":
            return line

        for separator in ("?=", ":=", "="):
            if separator not in line:
                continue

            line = line.rstrip()
            var, _ = line.split(separator, 1)
            var = var.strip()
            seen.add(var)
            if not var or var not in variables:
                continue

            fixed = f"{var}{separator}{variables[var]}"
            if line != fixed:
                # update_lines[line] = fixed
                updated.add(var)
                return fixed

        return line

    lines = contents.splitlines()
    output_lines = [fix_line(line) for line in lines]
    if updated:
        logger.debug(
            "Patched makefile %s variables: %s",
            filename,
            updated,
        )
    else:
        logger.debug("Makefile left unchanged: %s", filename)

    return output_lines, seen, updated


def patch_makefile(
    makefile: pathlib.Path,
    variables: dict[str, Any],
    dry_run: bool = False,
) -> set[str]:
    """
    Patch Makefile variable declarations with those provided in ``variables``.

    Parameters
    ----------
    makefile : pathlib.Path
        Path to the Makefile.
    variables : Dict[str, Any]
        Variable-to-value dictionary.

    Returns
    -------
    Set[str]
        Set of updated variables.
    """
    with open(makefile) as fp:
        contents = fp.read()

    output_lines, seen, updated = patch_makefile_contents(contents, variables, filename=makefile)
    if updated:
        if dry_run:
            logger.debug("Dry run, leaving Makefile %s unchanged", makefile)
        else:
            with open(makefile, "w") as fp:
                print("\n".join(output_lines), file=fp)
    else:
        logger.debug("Makefile left unchanged: %s", makefile)
    return updated


def add_dependencies_to_makefile_contents(
    contents: str,
    variables: dict[str, Any],
    filename: Optional[pathlib.Path | str] = None,
    prior_to: str = r"^EPICS_BASE\s*=",
) -> list[str]:
    """
    Patch Makefile variable declarations with those provided in ``variables``.

    New variables will be added as needed prior to ``EPICS_BASE``

    Parameters
    ----------
    makefile : pathlib.Path
        Path to the Makefile.
    variables : Dict[str, Any]
        Variable-to-value dictionary.

    Returns
    -------
    Set[str]
        Set of updated variables.
    """
    output_lines, seen, updated = patch_makefile_contents(
        contents,
        variables,
        filename=filename,
    )
    remaining = {
        variable: value for variable, value in variables.items()
        if variable not in updated and variable not in seen
    }
    if not remaining:
        return output_lines

    add_before_index = None
    for idx, line in enumerate(output_lines):
        if re.match(prior_to, line):
            add_before_index = idx
            break
    else:
        raise ValueError(
            f"Expression not found for adding new variables {prior_to!r} in {filename}",
        )

    for variable, value in reversed(remaining.items()):
        output_lines.insert(add_before_index, f"{variable}={value}")

    return output_lines


def add_dependencies_to_makefile(
    makefile: pathlib.Path,
    variables: dict[str, Any],
    dry_run: bool = False,
) -> set[str]:
    """
    Patch Makefile variable declarations with those provided in ``variables``.

    Parameters
    ----------
    makefile : pathlib.Path
        Path to the Makefile.
    variables : Dict[str, Any]
        Variable-to-value dictionary.

    Returns
    -------
    Set[str]
        Set of updated variables.
    """
    with open(makefile) as fp:
        contents = fp.read()

    output_lines, _, updated = patch_makefile_contents(contents, variables, filename=makefile)
    if updated:
        if dry_run:
            logger.debug("Dry run, leaving Makefile %s unchanged", makefile)
        else:
            with open(makefile, "w") as fp:
                print("\n".join(output_lines), file=fp)
    else:
        logger.debug("Makefile left unchanged: %s", makefile)
    return updated


def update_related_makefiles(
    base_path: pathlib.Path,
    makefile: Makefile,
    variable_to_value: dict[str, str],
) -> list[pathlib.Path]:
    """
    Update makefiles found during the introspection step that exist in ``base_path``.

    Updates module dependency paths based.

    Parameters
    ----------
    base_path : pathlib.Path
        The path to update makefiles under.
    makefile : Makefile
        The primary Makefile that contains paths of relevant included makefiles.
    """
    makefiles = set(makefile.makefile_list)

    patched = []
    # TODO: introspection of some makefiles can error out due to $(error dep not found)
    # which means we can't check the makefiles to update, which means it's
    # entirely broken...
    # TODO: add fallback method of trivial reading of Makefile for release variables
    # when the above fails.  Perhaps this fallback is good enough for the general
    # case and we shouldn't bother with whatrecord - at all? until everything's
    # sync'd?
    for path in [
        "configure/RELEASE",
        "configure/RELEASE.local",
    ]:
        if (base_path / path).exists():
            makefiles.add(path)

    for makefile_relative in sorted(makefiles):
        makefile_path = (base_path / makefile_relative).resolve()
        try:
            makefile_path.relative_to(base_path)
        except ValueError:
            logger.debug(
                "Skipping makefile: %s (not relative to %s)",
                makefile_path,
                base_path,
            )
            continue

        try:
            patch_makefile(makefile_path, variable_to_value)
        except PermissionError:
            logger.error(  # noqa: TRY400
                "Failed to patch makefile due to permissions: %s",
                makefile_path,
            )
        except Exception:
            logger.exception("Failed to patch makefile: %s", makefile_path)
        else:
            patched.append(makefile_path)

    return patched


@dataclass
class Libraries:
    """Libraries defined in the EPICS build system."""

    #: For all platforms.
    for_all: list[str] = field(default_factory=list)
    #: For the specific platform (designated by OS class).
    by_os_class: dict[str, list[str]] = field(default_factory=dict)
    #: For platforms without a corresponding OS class.
    default: list[str] = field(default_factory=list)

    def add_by_class(self, class_: str, value: str) -> None:
        if not class_:
            target_list = self.for_all
        elif class_ == "DEFAULT":
            target_list = self.default
        else:
            target_list = self.by_os_class.setdefault(class_, [])

        for lib in value.split():
            if lib not in target_list:
                target_list.append(lib)

    def get_libraries_for_os_class(self, os_class: str) -> list[str]:
        result = [*self.for_all]
        for lib in self.by_os_class.get(os_class, self.default):
            if lib not in result:
                result.append(lib)
        return result


@dataclass
class BuildSystemLibraries:
    """
    User or system libraries marked for usage in the EPICS build system.

    Per the EPICS documentation, libraries are linked in the following order.

    1. by_name
    <libname>_LIBS
    <libname>_LIBS_<osclass> or <libname>_LIBS_DEFAULT

    2a. lib - for linking libraries
    LIB_LIBS
    LIB_LIBS_<osclass> or LIB_LIBS_DEFAULT

    2b. prod - for linking the final product
    PROD_LIBS
    PROD_LIBS_<osclass> or PROD_LIBS_DEFAULT

    3. user
    USR_LIBS
    USR_LIBS_<osclass> or USR_LIBS_DEFAULT

    4. sys_by_name
    <libname>_SYS_LIBS
    <libname>_SYS_LIBS_<osclass> or <libname>_SYS_LIBS_DEFAULT

    5a. sys_lib - for linking system libraries with libraries
    LIB_SYS_LIBS
    LIB_SYS_LIBS_<osclass> or LIB_SYS_LIBS_DEFAULT

    5b. sys_prod - for linking system libraries with the final product
    PROD_SYS_LIBS
    PROD_SYS_LIBS_<osclass> or PROD_SYS_LIBS_DEFAULT

    6. sys_user
    USR_SYS_LIBS
    USR_SYS_LIBS_<osclass> or USR_SYS_LIBS_DEFAULT
    """

    by_name: dict[str, Libraries] = field(default_factory=dict)
    lib: Libraries = field(default_factory=Libraries)
    prod: Libraries = field(default_factory=Libraries)
    user: Libraries = field(default_factory=Libraries)

    sys_by_name: dict[str, Libraries] = field(default_factory=dict)
    sys_lib: Libraries = field(default_factory=Libraries)
    sys_prod: Libraries = field(default_factory=Libraries)
    sys_user: Libraries = field(default_factory=Libraries)

    def get_libraries_for_os_class(
        self,
        os_class: str,
        include_non_system: bool = False,
        name: Optional[str] = None,
    ) -> list[str]:
        libs = []
        if include_non_system:
            if name:
                if name in self.by_name:
                    libs.append(self.by_name[name])
            else:
                libs.extend(list(self.by_name.values()))
            libs.extend([self.lib, self.prod, self.user])

        if name:
            if name in self.by_name:
                libs.append(self.sys_by_name[name])
        else:
            libs.extend(list(self.sys_by_name.values()))
        libs.extend([self.sys_lib, self.sys_prod, self.sys_user])

        result = []
        for lib in libs:
            for name in lib.get_libraries_for_os_class(os_class):
                if name not in result:
                    result.append(name)
        return result



def recurse_makefiles(makefile: Makefile) -> Generator[Makefile, None, None]:
    seen = set()
    for directory in makefile.env.get("DIRS", "").split():
        if directory.startswith(".."):
            # Don' let it go out of the repo directory
            continue

        fn = makefile.working_directory / directory / "Makefile"
        if fn in seen:
            # We shouldn't see the same directory twice, but just in case
            continue

        seen.add(fn)
        if fn.exists():
            sub_makefile = Makefile.from_file(fn)
            yield sub_makefile
            yield from recurse_makefiles(sub_makefile)


def find_libraries_from_makefile(makefile: Makefile) -> BuildSystemLibraries:
    libs = BuildSystemLibraries()

    prefix_to_library = {
        "USR_LIBS": libs.user,
        "LIB_LIBS": libs.lib,
        "PROD_LIBS": libs.prod,

        "USR_SYS_LIBS": libs.sys_user,
        "PROD_SYS_LIBS": libs.sys_prod,
        "LIB_SYS_LIBS": libs.sys_lib,
        "SYS_PROD_LIBS": libs.sys_prod,  # deprecated, but that means nothing to us
    }
    for inner_makefile in recurse_makefiles(makefile):
        for key, value in inner_makefile.env.items():
            for prefix, lib in prefix_to_library.items():
                if key.startswith(prefix):
                    class_ = key.split(prefix)[1].lstrip("_")
                    lib.add_by_class(class_, value)
                    break
            else:
                if "_SYS_LIBS_" in key or key.endswith("_SYS_LIBS"):
                    name, class_ = key.split("_SYS_LIBS", 1)
                    if name not in libs.sys_by_name:
                        libs.sys_by_name[name] = Libraries()
                    libs.sys_by_name[name].add_by_class(class_.lstrip("_"), value)
                elif "_LIBS_" in key or key.endswith("_LIBS"):
                    name, class_ = key.split("_LIBS", 1)
                    if name not in libs.by_name:
                        libs.by_name[name] = Libraries()
                    libs.by_name[name].add_by_class(class_.lstrip("_"), value)

    return libs
