import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests against a running Reachy Mini MuJoCo simulator",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return

    skip = pytest.mark.skip(reason="Use --run-integration with a running simulator")
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip)
