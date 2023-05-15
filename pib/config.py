from __future__ import annotations

import json
import logging
import pathlib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import apischema
import yaml

from . import util

if TYPE_CHECKING:
    from .module import Module, VersionInfo
    try:
        from typing import Self
    except ImportError:
        from typing_extensions import Self


DEFAULT_SITE_CONFIG = util.MODULE_PATH / "default_config.json"
GIT_TEMPLATE = util.MODULE_PATH / "git_template"

logger = logging.getLogger(__name__)


def _default_path_norm() -> dict[str, str]:
    return {
        "/reg/g/pcds/(.*)$": r"/cds/group/pcds/\1",
    }


@dataclass
class SiteConfig:
    """Site settings for the builder."""

    epics_site_top: pathlib.Path = pathlib.Path("/cds/group/pcds/epics")
    module_path_regexes: list[str] = field(default_factory=list)
    base_path_regexes: list[str] = field(default_factory=list)
    extra_variables: dict[str, str] = field(default_factory=dict)
    base_url_branch: str = "https://github.com/slac-epics/epics-base/tree/{version}.branch"
    base_url_tag: str = "https://github.com/slac-epics/epics-base/releases/tag/{version}"
    git_url_template: str = "https://github.com/slac-epics/{name}"
    path_normalization: dict[str, str] = field(default_factory=_default_path_norm)

    git_template: pathlib.Path = GIT_TEMPLATE

    def get_git_url_for_version(self, version: VersionInfo) -> str:
        return self.git_url_template.format(
            name=version.name,
            base=version.base,
            tag=version.tag,
        )

    @classmethod
    def from_package(cls: type[Self]) -> Self:
        return cls.from_filename(DEFAULT_SITE_CONFIG)

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


    def normalize_path(self, path: pathlib.Path | str) -> pathlib.Path:
        """
        Normalize the provided path with the site normalization settings.

        Parameters
        ----------
        path : pathlib.Path | str

        Returns
        -------
        pathlib.Path
        """
        path_str = str(pathlib.Path(path).expanduser().resolve())

        for from_, normalize_to in self.path_normalization.items():
            old_path_str = path_str
            path_str = re.sub(from_, normalize_to, path_str)
            if old_path_str != path_str:
                logger.debug("Normalized path %s -> %s", old_path_str, path_str)

        return pathlib.Path(path_str)


@dataclass
class Settings:
    """Instance build settings, adding onto the site config."""

    epics_base: pathlib.Path = field(default_factory=pathlib.Path)
    support: pathlib.Path = field(default_factory=pathlib.Path)
    extra_variables: dict[str, str] = field(default_factory=dict)
    site: SiteConfig = field(default_factory=SiteConfig.from_package)

    def __post_init__(self) -> None:
        """Post-init fix up directories."""
        self.epics_base = self.epics_base.expanduser().resolve()
        self.support = self.support.expanduser().resolve()

    def set_base_version(
        self,
        base: Module,
    ) -> None:
        """Set the EPICS base version."""
        self.epics_base = base.install_path or self.site.epics_site_top / "base" / base.version
        if base.install_path is not None:
            # TODO get rid of this inconsistency
            self.support = self.site.epics_site_top / base.install_path.parts[-1] / "modules"
        else:
            self.support = self.site.epics_site_top / base.version / "modules"

    def get_path_for_module(self, module: Module) -> pathlib.Path:
        if module.install_path is not None:
            return module.install_path
        if module.name == "epics-base":
            return self.epics_base
        tag = module.version
        if "-branch" in tag:
            tag = tag.replace("-branch", "")
        return self.support / module.name / tag

    def get_path_for_version_info(self, version: VersionInfo) -> pathlib.Path:
        """
        Get the cache path for the provided dependency with version information.

        Parameters
        ----------
        version : VersionInfo
            The version information for the dependency, either derived by way
            of introspection or manually.

        Returns
        -------
        pathlib.Path

        """
        tag = version.tag
        if "-branch" in tag:
            tag = tag.replace("-branch", "")
        return self.support / version.name / tag

    @property
    def variables(self) -> dict[str, str]:
        variables = {
            "EPICS_BASE": str(self.epics_base),
            # TODO where do things like this go?
            # "EPICS_MODULES": str(self.support),
            # "SUPPORT": str(self.support),
            "RE2C": "re2c",
        }
        variables.update(self.site.extra_variables)
        variables.update(self.extra_variables)
        return variables
