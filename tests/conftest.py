from pathlib import Path

import pytest


@pytest.fixture
def project_tmp_path(tmp_path: Path) -> Path:
    return tmp_path
