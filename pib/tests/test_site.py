import pathlib
from pprint import pprint

import pytest

from pib.config import SiteConfig


@pytest.fixture()
def packaged_site_config() -> SiteConfig:
    return SiteConfig.from_package()


def test_load_site_config(packaged_site_config: SiteConfig):
    assert len(packaged_site_config.base_path_regexes) > 0
    assert len(packaged_site_config.module_path_regexes) > 0
    pprint(packaged_site_config)  # noqa: T203


@pytest.mark.parametrize(
    ("input_path", "output_path"),
    [
        ("/reg/g/pcds/epics/abc", "/cds/group/pcds/epics/abc"),
        ("/unmatched_path", "/unmatched_path"),
    ],
)
def test_normalize_path(
    packaged_site_config: SiteConfig,
    input_path: str,
    output_path: str,
) -> None:
    assert packaged_site_config.normalize_path(input_path) == pathlib.Path(output_path)
