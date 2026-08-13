"""桌面窗口非干扰约束的最小契约测试。"""

import unittest
from pathlib import Path


class TestWindowPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_js = (Path(__file__).resolve().parent.parent / "ui" / "src" / "main.js").read_text(
            encoding="utf-8")

    def test_knowledge_window_opens_at_right_edge(self):
        self.assertIn("workArea.width - w - 24", self.main_js)

    def test_knowledge_window_is_not_forced_always_on_top(self):
        start = self.main_js.index("function openKnowledgeWindow()")
        end = self.main_js.index('ipcMain.on("knowledge:open"', start)
        knowledge_block = self.main_js[start:end]
        self.assertNotIn("setAlwaysOnTop", knowledge_block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
