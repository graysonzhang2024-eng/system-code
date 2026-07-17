"""test_vault.py —— vault store 的考卷(单元测试)。

【为什么要这份考卷】
这个框架仓绝不碰真实数据,测试是它唯一的安全网:
以后任何人改了代码,只要跑一遍这份考卷全绿,就知道没弄坏地基。

【怎么跑】
    python3 -m pytest tests/            # 有 pytest 时
    python3 tests/test_vault.py         # 没 pytest 时也能直接跑(用标准库 unittest)

【测试思路:红 -> 绿】
先规定"输入 X 应得到 Y"(断言),再让代码去满足它。
每个 test_ 方法测一个动作;setUp 会准备一个临时仓,tearDown 清理,
全程只用临时目录里的假数据,零真实数据、零网络。
"""

import sys
import tempfile
import unittest
from pathlib import Path

# 让测试无论从哪运行都能找到 system_os 包(把仓根目录加进搜索路径)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_os.entity import ValidationError  # noqa: E402
from system_os.vault import Vault, build_document, parse_document  # noqa: E402


class TestParseBuild(unittest.TestCase):
    """测 frontmatter 的拆分与拼装(纯文本 <-> 结构化)。"""

    def test_parse_roundtrip(self):
        # 拼装再解析,应还原出同样的字段和正文(round-trip 往返一致性)
        meta = {"id": "x1", "status": "todo", "tags": ["a", "b"]}
        body = "正文内容\n第二行"
        text = build_document(meta, body)
        parsed_meta, parsed_body = parse_document(text)
        self.assertEqual(parsed_meta["id"], "x1")
        self.assertEqual(parsed_meta["status"], "todo")
        self.assertEqual(parsed_meta["tags"], ["a", "b"])
        self.assertEqual(parsed_body.strip(), body.strip())

    def test_parse_no_frontmatter(self):
        # 没有 frontmatter 的文件:meta 为空,全文当正文
        meta, body = parse_document("就是一段普通文字")
        self.assertEqual(meta, {})
        self.assertIn("普通文字", body)

    def test_parse_unclosed_frontmatter_raises(self):
        # 有起始 --- 但没结束 --- :应报错,而不是悄悄放过
        with self.assertRaises(ValidationError):
            parse_document("---\nid: x\n正文没有结束围栏")

    def test_chinese_preserved(self):
        # 中文应原样保留,不被转义成 \uXXXX
        text = build_document({"id": "x", "note": "买咖啡"}, "喝咖啡")
        self.assertIn("买咖啡", text)
        self.assertIn("喝咖啡", text)


class TestVaultCRUD(unittest.TestCase):
    """测管理员的五个动作。"""

    def setUp(self):
        # 每个测试前:开一个临时目录当仓,互不干扰
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Vault(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_and_read(self):
        self.vault.create("task-1", {"status": "todo"}, "买咖啡")
        rec = self.vault.read("task-1")
        self.assertEqual(rec["meta"]["id"], "task-1")
        self.assertEqual(rec["meta"]["status"], "todo")
        self.assertIn("买咖啡", rec["body"])
        # 管理员应自动盖上时间戳
        self.assertIn("created_at", rec["meta"])
        self.assertIn("updated_at", rec["meta"])

    def test_create_duplicate_raises(self):
        self.vault.create("task-1", {"status": "todo"})
        # 默认不允许覆盖已存在的 id
        with self.assertRaises(ValidationError):
            self.vault.create("task-1", {"status": "done"})

    def test_update_merges_fields(self):
        self.vault.create("task-1", {"status": "todo", "priority": "P1"})
        self.vault.update("task-1", {"status": "done"})
        rec = self.vault.read("task-1")
        self.assertEqual(rec["meta"]["status"], "done")   # 改了的
        self.assertEqual(rec["meta"]["priority"], "P1")    # 没动的应保留

    def test_update_refreshes_updated_at(self):
        self.vault.create("task-1", {"status": "todo"})
        before = self.vault.read("task-1")["meta"]["updated_at"]
        self.vault.update("task-1", {"status": "done"})
        after = self.vault.read("task-1")["meta"]["updated_at"]
        # 至少不应比原来早(时间戳被刷新)
        self.assertGreaterEqual(after, before)

    def test_delete(self):
        self.vault.create("task-1", {"status": "todo"})
        self.assertTrue(self.vault.exists("task-1"))
        self.vault.delete("task-1")
        self.assertFalse(self.vault.exists("task-1"))
        # 读一个已删的应报错
        with self.assertRaises(FileNotFoundError):
            self.vault.read("task-1")

    def test_delete_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.vault.delete("不存在的id")

    def test_list_with_filter(self):
        self.vault.create("t1", {"status": "todo", "priority": "P0"})
        self.vault.create("t2", {"status": "done", "priority": "P0"})
        self.vault.create("t3", {"status": "todo", "priority": "P2"})
        todos = list(self.vault.list(where={"status": "todo"}))
        self.assertEqual({r["meta"]["id"] for r in todos}, {"t1", "t3"})
        p0_todo = list(self.vault.list(where={"status": "todo", "priority": "P0"}))
        self.assertEqual({r["meta"]["id"] for r in p0_todo}, {"t1"})

    def test_invalid_domain_raises(self):
        # domain 只能是 work/personal,填别的应被校验拦下
        with self.assertRaises(ValidationError):
            self.vault.create("t1", {"domain": "外星"})

    def test_id_with_slash_raises(self):
        with self.assertRaises(ValidationError):
            self.vault.create("a/b", {"status": "todo"})


class TestReadFixture(unittest.TestCase):
    """测能读真实格式的 fixtures 样例文件。"""

    def test_read_sample_fixture(self):
        fixtures = Path(__file__).resolve().parent.parent / "fixtures" / "work"
        vault = Vault(fixtures)
        rec = vault.read("sample-task-0001")
        self.assertEqual(rec["meta"]["id"], "sample-task-0001")
        self.assertEqual(rec["meta"]["priority"], "P2")
        self.assertIn("脱敏样例", rec["body"])


if __name__ == "__main__":
    # 没装 pytest 也能直接 python3 tests/test_vault.py 跑
    unittest.main(verbosity=2)
