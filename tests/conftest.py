import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MINDFORGE_NO_SOUND", "1")
os.environ.setdefault("MINDFORGE_NO_SPEECH", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture
def storage(tmp_path):
    from mindforge.storage import Storage

    st = Storage(tmp_path / "test.db")
    yield st
    st.close()
