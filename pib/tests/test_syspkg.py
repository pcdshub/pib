import shutil
from typing import Optional

import pytest

from .. import syspkg
from ..spec import Requirements


@pytest.mark.parametrize(
    ("package_manager", "sudo", "expected"),
    [
        pytest.param(
            "yum",
            True,
            ["sudo", "yum", "-y", "install"],
            id="yum-sudo",
        ),
        pytest.param(
            "yum",
            False,
            ["yum", "-y", "install"],
            id="yum-nosudo",
        ),
        pytest.param(
            "apt",
            True,
            ["sudo", "apt-get", "install", "-y"],
            id="apt-sudo",
        ),
        pytest.param(
            "apt",
            False,
            ["apt-get", "install", "-y"],
            id="apt-nosudo",
        ),
        pytest.param(
            "brew",
            False,
            ["brew", "install"],
            id="brew-nosudo",
        ),
        pytest.param(
            "conda",
            False,
            ["my-conda-path", "install", "-y"],
            id="conda-nosudo",
        ),
    ],
)
def test_get_command(
    monkeypatch: pytest.MonkeyPatch,
    package_manager: str,
    sudo: bool,
    expected: list[str],
):
    def which_conda(*_) -> str:  # noqa: ANN002
        return "my-conda-path"

    packages = ["pkg"]
    monkeypatch.setattr(shutil, "which", which_conda)
    commands = syspkg.PackageManager[package_manager].get_commands(packages=packages, sudo=sudo)
    assert commands == [expected + packages]


def test_get_full_command(monkeypatch: pytest.MonkeyPatch):
    def which_conda(*_) -> str:  # noqa: ANN002
        return "my-conda-path"

    reqs = Requirements(conda=["a", "b", "c"])
    monkeypatch.setattr(shutil, "which", which_conda)
    assert syspkg.get_install_commands(reqs, "conda") == [["my-conda-path", "install", "-y", "a", "b", "c"]]


@pytest.mark.parametrize(
    ("executable", "package_manager"),
    [
        ("yum", "yum"),
        ("apt-get", "apt"),
        ("brew", "brew"),
    ],
)
def test_guess_package_manager(
    monkeypatch: pytest.MonkeyPatch,
    executable: str,
    package_manager: str,
):
    def which(cmd: str) -> Optional[str]:
        if cmd == executable:
            return cmd
        return None

    monkeypatch.setattr(shutil, "which", which)
    assert syspkg.guess_package_manager() == syspkg.PackageManager[package_manager]


def test_yum_groupinstall():
    reqs = Requirements(yum=["group:'Development Tools'", "re2c"])
    assert syspkg.get_install_commands(reqs, "yum", sudo=True) == [
        ["sudo", "yum", "-y", "groupinstall", "Development Tools"],
        ["sudo", "yum", "-y", "install", "re2c"],
    ]
