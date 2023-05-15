import pytest

from pib import makefile


@pytest.mark.parametrize(
    ("input_contents", "variables", "expected_output", "changed"),
    [
        pytest.param(
            "A=1\nB=2\nC=3",
            {"A": "1", "B": "5", "C": "7"},
            "A=1\nB=5\nC=7\n",
            {"B", "C"},
            id="simple",
        ),
        pytest.param(
            "A=1\nB=2\nC=3",
            {"A": "1", "B": "5", "D": "7"},
            "A=1\nB=5\nC=3\n",
            {"B"},
            id="missing",
        ),
        pytest.param(
            "A=1\nB:=2\nC?=3",
            {"A": "2", "B": "5", "C": "7"},
            "A=2\nB:=5\nC?=7\n",
            {"A", "B", "C"},
            id="equals-variants",
        ),
    ],
)
def test_patch_makefile(input_contents: str, variables: dict[str, str], expected_output: str, changed: set[str]):
    result_lines, _, result_changed = makefile.patch_makefile_contents(input_contents, variables=variables, filename=None)
    assert result_lines == expected_output.splitlines()
    assert result_changed == changed


@pytest.mark.parametrize(
    ("input_contents", "variables", "expected_output"),
    [
        pytest.param(
            "A=1\nB=2\nC=3\nEPICS_BASE=",
            {"A": "1", "B": "5", "C": "7", "D": "0"},
            "A=1\nB=5\nC=7\nD=0\nEPICS_BASE=\n",
            id="simple",
        ),
        pytest.param(
            "A=1\nB=2\nC=3\nEPICS_BASE=",
            {"Q": "100"},
            "A=1\nB=2\nC=3\nQ=100\nEPICS_BASE=\n",
            id="just-add",
        ),
    ],
)
def test_patch_add_makefile(input_contents: str, variables: dict[str, str], expected_output: str):
    result_lines = makefile.add_dependencies_to_makefile_contents(
        input_contents,
        variables=variables,
        filename=None,
    )
    assert result_lines == expected_output.splitlines()
