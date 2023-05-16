"""`pib` is the top-level command for accessing various subcommands."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import shlex
import subprocess
import sys
import typing
from typing import Optional, TypedDict, cast

import apischema
import click
import yaml

from . import build, config, exceptions, syspkg
from .config import DEFAULT_SITE_CONFIG
from .spec import Application, Module, SpecificationFile

if typing.TYPE_CHECKING:
    import io
    from collections.abc import Generator

DESCRIPTION = __doc__
AUTO_ENVVAR_PREFIX = "PIB"

logger = logging.getLogger(__name__)


class ExitedWithError(Exception):
    """CLI exited with a non-zero error code."""

    code: int | str | None

    def __init__(self, message: str, code: int | str | None) -> None:
        super().__init__(message)
        self.code = code


class CliContext(TypedDict):
    """Click CLI context dictionary."""

    specs: build.Specifications
    exclude_modules: list[str]
    only_modules: list[str]


def get_included_modules(ctx: click.Context) -> Generator[Module, None, None]:
    """
    Get all modules from the specifications to be included, based on user settings.

    Parameters
    ----------
    ctx : click.Context

    Yields
    ------
    Module
    """
    info = cast(CliContext, ctx.obj)

    for module in info["specs"].modules:
        if build.should_include(module, info["only_modules"], info["exclude_modules"]):
            yield module
        else:
            logger.debug("Skipping module: %s", module.name)


def print_version(
    ctx: click.Context,
    param: click.Parameter,  # noqa: ARG001
    value: bool,
) -> None:
    """Print the version number and exit."""
    if not value or ctx.resilient_parsing:
        return

    from . import __version__
    print(__version__)  # noqa: T201
    ctx.exit()


def get_spec_files_from_env() -> list[pathlib.Path]:
    """
    Get specification file paths from the environment.

    PIB_SPEC_FILES is an environment variable that can be used in addition
    to command-line parameters to tell pib which specification files to load.

    Returns
    -------
    list[pathlib.Path]
    """
    # NOTE: gather env vars and add them to the list
    # TODO: this is not what click would do normally; is this OK?
    spec_files = []
    env_paths = os.environ.get(f"{AUTO_ENVVAR_PREFIX}_SPEC_FILES", "")
    if env_paths:
        for path_str in reversed(env_paths.split(os.pathsep)):
            path = pathlib.Path(path_str).expanduser().resolve()
            if path not in spec_files:
                logger.debug("Adding spec file from environment: %s", path)
                spec_files.insert(0, path)
            else:
                logger.debug("Spec file from environment already in list: %s", path)
    return spec_files


def configure_cli_context(
    spec_files: list[str | pathlib.Path],
    site_config: str | pathlib.Path,
    exclude_modules: list[str],
    exclude_from: list[str | pathlib.Path],
    only_modules: list[str],
) -> CliContext:
    """
    Configure the CLI context dictionary from command-line arguments.

    Parameters
    ----------
    spec_files : list[str | pathlib.Path]
    site_config : str | pathlib.Path
    exclude_modules : list[str]
    exclude_from : list[str | pathlib.Path]
    only_modules : list[str]

    Returns
    -------
    CliContext
    """
    exclude_modules = list(exclude_modules)
    exclude_from = list(exclude_from)
    only_modules = list(only_modules)
    spec_files = list(spec_files)

    # click doesn't seem to like how we use environment variables. Do a bit
    # of munging of env vars and CLI arguments here to get the final list
    # of spec files.
    for env_spec in reversed(get_spec_files_from_env()):
        if env_spec not in spec_files:
            logger.debug("Addingspec file from env: %s", env_spec)
            spec_files.insert(0, env_spec)
    logger.debug("Final spec file list: %s", spec_files)

    specs = build.Specifications()
    specs.settings.site = config.SiteConfig.from_filename(site_config)
    logger.debug("Site configuration: %s", specs.settings.site)
    for spec in spec_files:
        specs.add_spec_by_filename(spec)

    for name in exclude_modules:
        try:
            module = specs.find_module_by_name(name)
        except exceptions.EpicsModuleNotFoundError:
            logger.warning("Excluded modules: %s", exclude_modules)
        else:
            logger.debug("Excluding module: %s", module)

    exclude_from_specs = build.Specifications.from_spec_files(exclude_from)

    if exclude_from_specs.modules:
        logger.debug("Excluding modules from files: %s", exclude_from)
        for module in exclude_from_specs.all_modules:
            if module.name not in exclude_modules and module.variable not in exclude_modules:
                logger.debug("Excluding module: %s", module)
                exclude_modules.append(module.name)

    return {
        "specs": specs,
        "exclude_modules": exclude_modules,
        "only_modules": only_modules,
    }


@click.group(chain=True)
@click.pass_context
@click.option(
    "-l",
    "--log",
    "log_level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="INFO",
)
@click.option(
    "--version",
    is_flag=True,
    callback=print_version,
    expose_value=False,
    is_eager=True,
)
@click.option(
    "-s",
    "--spec",
    "spec_files",  # -> env: PIB_SPEC_FILES with [semi]colon delimiter
    help="Spec filenames to load",
    type=click.Path(
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        allow_dash=True,  # <-- TODO support stdin
        path_type=pathlib.Path,
    ),
    multiple=True,
    required=True,
)
@click.option(
    "--site",
    "site_config",  # -> env: PIB_SITE_CONFIG
    help="Site configuration file to load",
    type=click.Path(
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        allow_dash=False,
        path_type=pathlib.Path,
    ),
    default=DEFAULT_SITE_CONFIG,
    multiple=False,
    required=False,
)
@click.option(
    "--exclude",
    "exclude_modules",
    help=(
        "Exclude these modules when performing actions, "
        "by variable name or spec-defined name"
    ),
    type=str,
    multiple=True,
    required=False,
)
@click.option(
    "--exclude-from",
    "exclude_from",
    help="Exclude modules from this file when performing actions",
    type=click.Path(
        exists=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        allow_dash=False,  # <-- TODO support stdin
        path_type=pathlib.Path,
    ),
    multiple=True,
    required=False,
)
@click.option(
    "--only",
    "only_modules",
    help="Include only these modules (by variable name or spec-defined name)",
    type=str,
    multiple=True,
    required=False,
)
# @click.option(
#     "--only-from",
#     "only_from",
#     help="Include modules from this file when performing actions",
#     type=click.Path(
#         exists=True,
#         dir_okay=False,
#         readable=True,
#         resolve_path=True,
#         allow_dash=False,  # <-- TODO support stdin
#         path_type=pathlib.Path,
#     ),
#     multiple=True,
#     required=False,
# )
def cli(
    ctx: click.Context,
    *,
    log_level: str,
    spec_files: list[str | pathlib.Path],
    site_config: str | pathlib.Path,
    exclude_modules: list[str],
    exclude_from: list[str | pathlib.Path],
    only_modules: list[str],
    # only_from: list[str | pathlib.Path],
) -> None:
    logger.info(
        f"Main: {log_level=} {spec_files=} {exclude_modules=} "
        f"{only_modules=} {exclude_from=}",
    )
    ctx.ensure_object(dict)

    module_logger = logging.getLogger("pib")
    module_logger.setLevel(log_level)
    logging.basicConfig()

    cli_context = configure_cli_context(
        spec_files=spec_files,
        site_config=site_config,
        exclude_modules=exclude_modules,
        exclude_from=exclude_from,
        only_modules=only_modules,
    )
    ctx.obj.update(**cli_context)
    logger.debug("Click CLI context is: %s", ctx.obj)


@cli.command(
    "build",
    help="Recursively build everything in the spec",
)
@click.option(
    "--stop-on-failure/--continue-on-failure",
    default=True,
    help="Stop builds on the first failure",
)
@click.pass_context
def cli_build(ctx: click.Context, stop_on_failure: bool = False) -> None:
    logger.info(f"Build: {stop_on_failure=}")
    info = cast(CliContext, ctx.obj)
    try:
        return build.build(
            info["specs"],
            stop_on_failure=stop_on_failure,
            skip=info["exclude_modules"],
        )
    except exceptions.ProgramExecutionError as ex:
        logger.exception("Failed to build as command returned an error")
        click.echo("Output:")
        click.echo(ex.output)
        ctx.exit(1)


@cli.command(
    "download",
    help="Download modules listed in the spec files, optionally ",
)
@click.option(
    "--patch/--no-patch",
    "patch",
    default=True,
    help="Patch files after downloading",
)
# @click.option(
#     "--include-deps/--exclude-deps",
#     default=True,
#     help="Do not download dependencies",
# )
@click.pass_context
def cli_download(
    ctx: click.Context,
    patch: bool = True,
    # include_deps: bool,
    # release_site: bool,
) -> None:
    logger.info("Download")
    info = cast(CliContext, ctx.obj)
    logger.warning("Got site configuration: %s", info["specs"].settings.site)

    build.download_spec_modules(
        info["specs"],
        # include_deps=include_deps,
        skip=info["exclude_modules"],
        only=info["only_modules"],
        exist_ok=True,
        patch=patch,
    )


@cli.command(
    "release_site",
    help="Create a RELEASE_SITE file.",
)
@click.option(
    "--output",
    help="Path to write release_site file to",
    type=click.Path(
        dir_okay=False,
        path_type=pathlib.Path,
    ),
    default=None,
    required=False,
)
@click.pass_context
def cli_release_site(ctx: click.Context, output: Optional[pathlib.Path]) -> None:
    logger.info("RELEASE_SITE")
    info = cast(CliContext, ctx.obj)
    build.create_release_site(info["specs"], path=output)


@cli.command(
    "patch",
    help="Apply patches from spec files",
)
@click.pass_context
def cli_patch(ctx: click.Context) -> None:
    logger.info("Patch")
    info = cast(CliContext, ctx.obj)
    specs = info["specs"]
    for module in get_included_modules(ctx):
        build.patch_module(module, specs.settings)


@cli.command(
    "inspect",
    help="Introspect an IOC/module and [optionally] recursively download dependencies",
)
@click.argument(
    "ioc_path",
    type=click.Path(
        exists=True,
        dir_okay=True,
        file_okay=False,
        readable=True,
        resolve_path=True,
        allow_dash=False,
        path_type=pathlib.Path,
    ),
    required=True,
)
@click.option(
    "-o",
    "--output",
    # help="Path to write to (stdout by default)",
    type=click.File(
        mode="wt",
        lazy=True,
    ),
    default=sys.stdout,
)
@click.option(
    "--download/--no-download",
    default=True,
    help="Download missing dependencies and recursively inspect them",
)
@click.pass_context
def cli_inspect(
    ctx: click.Context,
    ioc_path: pathlib.Path,
    output: io.TextIOBase,
    download: bool = True,
    # recurse: bool = True,
    # name: str = "",
    # variable_name: str = "",
) -> None:
    logger.info(
        "Inspect: ioc_path=%s output=%s download=%s",
        ioc_path, output, download,
    )

    info = cast(CliContext, ctx.obj)
    specs = info["specs"]
    specs.check_settings()

    app = Application()
    extra_modules = []
    specs.applications[ioc_path] = app

    logger.debug("Checking for makefile in path: %s", ioc_path)
    logger.debug(
        "EPICS base path for introspection: %s (%s)",
        specs.settings.epics_base,
        specs.settings,
    )

    inspector = build.RecursiveInspector.from_path(ioc_path, specs)
    if download:
        inspector.download_missing_dependencies()

    for variable, version in inspector.variable_to_version.items():
        if variable in specs.variable_name_to_module:
            app.standard_modules.append(variable)
        else:
            extra_modules.append(version.to_module(variable, settings=specs.settings))

    file = SpecificationFile(
        application=app,
        modules=extra_modules,
    )
    serialized = apischema.serialize(
        SpecificationFile,
        file,
        exclude_defaults=True,
        exclude_none=True,
    )
    result = yaml.dump(serialized, indent=2, sort_keys=False)

    logger.debug("Writing to %s:\n'''\n%s\n'''", output, result)
    output.write(result)

    if output is not sys.stdout:
        output.flush()
        output.close()


@cli.command(
    "parse",
    help="Parse the spec files and output a JSON summary",
)
@click.pass_context
def cli_parse(ctx: click.Context) -> None:
    # TODO: remove?
    logger.info("Parse")
    info = cast(CliContext, ctx.obj)

    specs = info["specs"]
    serialized = apischema.serialize(build.Specifications, specs)
    print(json.dumps(serialized, indent=2))  # noqa: T201


@cli.command(
    "requirements",
    help="Summarize and/or install package manager requirements",
)
@click.option(
    "--source",
    "sources",
    required=False,
    type=click.Choice(["yum", "apt", "conda", "brew"]),
    multiple=True,
    default=("apt", "conda"),
)
@click.option(
    "--type",
    "type_",
    required=True,
    type=click.Choice(["build", "run"]),
    help="Select build or runtime requirements",
)
@click.option(
    "--conda-path",
    required=False,
    type=str,
    default=None,
)
@click.option(
    "--sudo/--no-sudo",
    "sudo",
    help="Use sudo for system package managers",
    default=True,
)
@click.option(
    "--install/--show",
    "install",
    help="Just show or install dependencies",
    default=False,
)
@click.pass_context
def cli_requirements(
    ctx: click.Context,
    *,
    sources: Optional[list[str]] = None,
    type_: str = "build",
    sudo: bool = True,
    conda_path: str = "conda",
    install: bool = False,
) -> None:
    logger.info("Requirements: sources=%s install=%s (sudo=%s)", sources, install, sudo)
    info = cast(CliContext, ctx.obj)
    specs = info["specs"]

    if type_ == "build":
        requires = specs.build_requires
    elif type_ == "run":
        requires = specs.run_requires
    else:
        raise ValueError(f"Unsupported requirement type: {type_}")

    click.echo(json.dumps(syspkg.requirements_to_dict(requires), indent=2))

    if not install:
        return

    for source in sources or [syspkg.guess_package_manager(), "conda"]:
        logger.info("Installing %s dependencies", source)
        for command in syspkg.get_install_commands(
            requires,
            source,
            sudo=sudo,
            conda_path=conda_path,
        ):
            str_command = shlex.join(command)
            logger.info("%s install running: %s", source, str_command)
            if subprocess.check_call(command) != 0:  # noqa: S603
                raise exceptions.RequirementInstallationFailedError(
                    f"Command was: {str_command}",
                )


@cli.command(
    "sync",
    help="Synchronize paths for all dependencies (RELEASE file variables)",
)
@click.pass_context
def cli_sync(ctx: click.Context) -> None:
    logger.info("Sync")
    info = cast(CliContext, ctx.obj)
    specs = info["specs"]

    logger.info(
        "Synchronizing dependencies with these paths:\n    %s",
        "\n    ".join(
            f"{var}={value}" for var, value in specs.variable_name_to_path.items()
        ),
    )
    build.sync(specs, skip=info["exclude_modules"])


@cli.command(
    "please",
    help="Shortcut: download, release_site, patch, synchronize paths, and build all using defaults",
)
@click.option(
    "--app",
    type=click.Path(
        exists=True,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        allow_dash=False,
        path_type=pathlib.Path,
    ),
    help="Inspect and build this application, too",
    required=False,
    default=None,
)
@click.pass_context
def cli_please(
    ctx: click.Context,  # noqa: ARG001
    app: Optional[pathlib.Path] = None,
) -> None:
    logger.info("pib, please do the thing")
    pib_args = sys.argv[1:sys.argv.index("please")]

    # 1. Install any system package requirements
    try:
        run_cli_programmatically(
            *pib_args,
            "requirements",
            "--install",
            "--type",
            "build",
            "--source",
            syspkg.guess_package_manager().name,
            "--source",
            "conda",
        )
    except ExitedWithError as ex:
        logger.exception("Dependency installation failed")
        sys.exit(ex.code)

    # 2. Download epics-base and modules
    # 3. Create a RELEASE_SITE file
    # 4. Synchronize all RELEASE/build system files
    # 5. Build base and common modules
    for command in (
        "download",
        "release_site",
        "sync",
        "build",
    ):
        try:
            run_cli_programmatically(*pib_args, command)
        except ExitedWithError as ex:
            logger.exception("Command %r failed", command)
            sys.exit(ex.code)

    if not app:
        return

    logger.info("Inspecting and building the app in %s")

    # 6. Inspect the provided application, using above already-existing
    #    module versions and recording newly-specified ones in 'pib.yaml'
    app_conf = app / "pib.yaml"
    if not app_conf.exists():
        try:
            run_cli_programmatically(
                *pib_args,
                "inspect",
                str(app),
                "-o",
                str(app_conf),
            )
        except ExitedWithError as ex:
            logger.exception("Application inspection failed")
            sys.exit(ex.code)

    # Add on the app spec file to the args
    pib_args = ["-s", str(app_conf), *pib_args]

    # 7. Download any new modules, as necessary
    # 8. Synchronize paths with all modules
    # 9. Buid the application
    for command in (
        "download",
        "sync",
        "build",
    ):
        try:
            run_cli_programmatically(*pib_args, command)
        except ExitedWithError as ex:
            logger.exception("Command %r failed", command)
            sys.exit(ex.code)


def run_cli_programmatically(*args: str) -> None:
    """
    Run the pib CLI with the provided arguments.

    This helper allows for the environment variable prefix to be set and
    also helps catch SystemExit such that a sequence of CLI executions can be
    performed without being interrupted.  If one step fails, ``ExitedWithError``
    will be raised.

    Parameters
    ----------
    *args : str
        Command-line parameters to pass to the main ``pib`` CLI entrypoint.
    """
    try:
        cli(list(args), auto_envvar_prefix=AUTO_ENVVAR_PREFIX)
    except SystemExit as ex:
        code = ex.code
        if not isinstance(code, int) or code != 0:
            raise ExitedWithError(f"CLI exited with error code {code}", code=code) from ex


def main() -> None:
    """Primary entrypoint for pib."""
    try:
        return run_cli_programmatically(*sys.argv[1:])
    except ExitedWithError as ex:
        sys.exit(ex.code)


if __name__ == "__main__":
    main()
