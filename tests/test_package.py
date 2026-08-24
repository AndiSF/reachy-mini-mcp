from importlib.metadata import version
from reachy_mini_mcp import __version__

PACKAGE_NAME = "reachy-mini-mcp"


class TestPackageVersion:
    def test_matches_installed_metadata(self):
        # Arrange
        expected_version = version(PACKAGE_NAME)

        # Act
        actual_version = __version__

        # Assert
        assert actual_version == expected_version
