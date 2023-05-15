import pathlib


class DownloadFailureError(Exception):
    """Download failure."""

    ...


class SpecificationError(Exception):
    """Specification file error."""

    ...


class EpicsModuleNotFoundError(ValueError):
    """User-specified module name was not found."""

    ...


class TargetDirectoryAlreadyExistsError(RuntimeError):
    """Target directory already exists."""

    path: pathlib.Path


class InvalidSpecificationError(SpecificationError):
    """Invalid specification."""

    ...


class EpicsBaseOnlyOnceError(SpecificationError):
    """epics-base specified multiple times."""

    ...


class EpicsBaseMissingError(Exception):
    """epics-base missing from specification."""

    ...


class BuildError(Exception):
    """Build failure."""

    ...


class ProgramExecutionError(BuildError):
    """Program execution was unsuccessful."""

    exit_code: int
    output: str

    def __init__(self, msg: str, exit_code: int, output: str) -> None:
        super().__init__(msg)
        self.exit_code = exit_code
        self.output = output


class MakeError(ProgramExecutionError):
    """Make execution was unsuccessful."""


class ProgramMissingError(Exception):
    """Required program is missing."""

    ...


class RequirementInstallationFailedError(Exception):  # ProgramExecutionError
    """Required program is missing."""

    ...
