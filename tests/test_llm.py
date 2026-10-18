"""Tests for app/core/llm.py without the network: only where the settings are loaded from."""
import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import core.llm  # noqa: E402


class EnvFile(unittest.TestCase):
    def test_loads_only_the_repo_root_env_by_exact_path(self):
        with mock.patch("dotenv.load_dotenv") as load:
            importlib.reload(core.llm)
        importlib.reload(core.llm)
        load.assert_called_once_with(ROOT / ".env")
        self.assertEqual(core.llm.ENV_FILE, ROOT / ".env")


if __name__ == "__main__":
    unittest.main()
