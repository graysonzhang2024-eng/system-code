"""机器身份配置的回归测试。"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_os import config, machine  # noqa: E402


class TestMachineConfigPriority(unittest.TestCase):
    def setUp(self):
        self._old_machine_id = os.environ.pop("MACHINE_ID", None)
        self._dotenv = patch.object(config, "_DOTENV", {})
        self._dotenv.start()

    def tearDown(self):
        self._dotenv.stop()
        if self._old_machine_id is None:
            os.environ.pop("MACHINE_ID", None)
        else:
            os.environ["MACHINE_ID"] = self._old_machine_id

    def test_process_environment_wins_over_dotenv_and_hostname(self):
        os.environ["MACHINE_ID"] = " PERSONAL "
        config._DOTENV["MACHINE_ID"] = "work"
        with patch.object(machine.socket, "gethostname", return_value="work-laptop"):
            self.assertEqual(machine.detect_machine(), "personal")

    def test_dotenv_wins_over_hostname(self):
        config._DOTENV["MACHINE_ID"] = " PERSONAL "
        with patch.object(machine.socket, "gethostname", return_value="company-workstation"):
            self.assertEqual(machine.detect_machine(), "personal")

    def test_invalid_environment_value_falls_through_to_valid_dotenv(self):
        os.environ["MACHINE_ID"] = "office"
        config._DOTENV["MACHINE_ID"] = "personal"
        with patch.object(machine.socket, "gethostname", return_value="work-laptop"):
            self.assertEqual(machine.detect_machine(), "personal")

    def test_invalid_explicit_values_fall_through_to_hostname(self):
        os.environ["MACHINE_ID"] = "office"
        config._DOTENV["MACHINE_ID"] = "private"
        with patch.object(machine.socket, "gethostname", return_value="my-home-mac"):
            self.assertEqual(machine.detect_machine(), "personal")

    def test_unknown_hostname_defaults_to_work(self):
        os.environ["MACHINE_ID"] = ""
        config._DOTENV["MACHINE_ID"] = ""
        with patch.object(machine.socket, "gethostname", return_value="macbook-pro"):
            self.assertEqual(machine.detect_machine(), "work")

    def test_machine_letter_uses_dotenv_identity(self):
        config._DOTENV["MACHINE_ID"] = "personal"
        self.assertEqual(machine.machine_letter(), "p")


if __name__ == "__main__":
    unittest.main(verbosity=2)
