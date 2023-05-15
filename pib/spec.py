from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Optional

import apischema
import yaml

if TYPE_CHECKING:
    try:
        from typing import Self
    except ImportError:
        from typing_extensions import Self


@dataclass
class MakeOptions:
    """Make options."""

    args: list[str] = field(default_factory=list)
    parallel: int = 1
    clean: bool = True


@dataclass
class GitSource:
    """Git source for a module/IOC."""

    url: str
    tag: str
    args: Optional[str] = ""
    depth: int = 5
    recursive: bool = True


@dataclass
class Requirements:
    """Requirements for a module/IOC."""

    yum: list[str] = field(default_factory=list)
    apt: list[str] = field(default_factory=list)
    conda: list[str] = field(default_factory=list)
    brew: list[str] = field(default_factory=list)


@dataclass
class Patch:
    """Patch to apply."""

    description: str
    dest_file: str
    method: Literal["replace", "patch"] = "replace"
    mode: Optional[int] = None
    contents: Optional[str] = None
    patch_file: Optional[str] = None


@dataclass
class Module:
    """EPICS module specification."""

    name: str
    variable: str = ""
    install_path: Optional[pathlib.Path] = None
    git: Optional[GitSource] = None
    patches: list[Patch] = field(default_factory=list)
    make: Optional[MakeOptions] = field(default_factory=MakeOptions)
    build_requires: Optional[Requirements] = field(default_factory=Requirements)
    run_requires: Optional[Requirements] = field(default_factory=Requirements)

    def __post_init__(self) -> None:
        """Fix up defaults, if necessary."""
        if not self.variable:
            self.variable = self.name.replace("-", "_").upper()

    @property
    def version(self) -> str:
        """Get module version number."""
        if self.git is not None:
            return self.git.tag
        raise NotImplementedError

    def __str__(self) -> str:
        """Get module string information."""
        return f"<Module {self.name} ({self.variable})={self.version}>"


@dataclass
class Application:
    """EPICS application specification."""

    binary: str = ""
    standard_modules: list[str] = field(default_factory=list)
    build_requires: Optional[Requirements] = field(default_factory=Requirements)
    run_requires: Optional[Requirements] = field(default_factory=Requirements)
    make: Optional[MakeOptions] = field(default_factory=MakeOptions)
    # extra modules just go top-level?
    # extra_modules: list[Module] = field(default_factory=list)


@dataclass
class SpecificationFile:
    """IOC/module .spec specification file."""

    modules: list[Module] = field(default_factory=list)
    application: Optional[Application] = None

    @property
    def modules_by_name(self) -> dict[str, Module]:
        return {module.name: module for module in self.modules}

    @classmethod
    def from_filename(cls: type[Self], filename: pathlib.Path | str) -> Self:
        is_json = pathlib.Path(filename).suffix.lower() in {".json"}
        with open(filename) as fp:
            contents = fp.read()

        if is_json:
            serialized = json.loads(contents)
        else:
            serialized = yaml.load(contents, Loader=yaml.SafeLoader)
        return apischema.deserialize(cls, serialized)
