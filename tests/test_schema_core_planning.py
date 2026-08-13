"""test_schema_core_planning.py —— planning / decision / rule 校验与治理钩子的考卷。

怎么跑:
    python3 -m pytest tests/
    python3 tests/test_schema_core_planning.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_os.entity import ValidationError  # noqa: E402
from system_os.schema_core import (  # noqa: E402
    check_decision_guard,
    validate_decision,
    validate_rule,
)
from system_os.schema_work import validate_planning  # noqa: E402
from system_os.vault import Vault  # noqa: E402


# ---------------- planning ----------------
class TestPlanning(unittest.TestCase):
    def _base(self, **ov):
        m = {
            "id": "plan-x", "title": "目标", "type": "milestone",
            "horizon": "quarter", "category": "事业", "status": "active",
            "domain": "work", "source_machine": "work",
        }
        m.update(ov)
        return m

    def test_valid(self):
        validate_planning(self._base())

    def test_bad_type(self):
        with self.assertRaises(ValidationError):
            validate_planning(self._base(type="梦想"))

    def test_bad_horizon(self):
        with self.assertRaises(ValidationError):
            validate_planning(self._base(horizon="下辈子"))

    def test_missing_status(self):
        m = self._base()
        del m["status"]
        with self.assertRaises(ValidationError):
            validate_planning(m)


# ---------------- decision ----------------
class TestDecision(unittest.TestCase):
    def _base(self, **ov):
        m = {
            "id": "dec-x", "title": "选型", "date": "2026-07-17",
            "status": "decided", "domain": "work", "source_machine": "work",
        }
        m.update(ov)
        return m

    def test_valid_minimal(self):
        validate_decision(self._base())

    def test_bad_status(self):
        with self.assertRaises(ValidationError):
            validate_decision(self._base(status="纠结中"))

    def test_bad_reversibility(self):
        with self.assertRaises(ValidationError):
            validate_decision(self._base(reversibility="半开门"))

    def test_options_must_be_list(self):
        with self.assertRaises(ValidationError):
            validate_decision(self._base(options="A或B"))


# ---------------- 治理钩子 ----------------
class TestDecisionGuard(unittest.TestCase):
    def test_low_energy_oneway_blocked(self):
        # 低电 + 不可逆 + 已决 → 被拦
        meta = {
            "status": "decided", "reversibility": "one_way_door",
            "energy_context": "drain",
        }
        with self.assertRaises(ValidationError):
            check_decision_guard(meta)

    def test_low_energy_twoway_ok(self):
        # 低电但可逆 → 放行
        meta = {
            "status": "decided", "reversibility": "two_way_door",
            "energy_context": "drain",
        }
        check_decision_guard(meta)

    def test_high_energy_oneway_ok(self):
        # 不可逆但清醒 → 放行
        meta = {
            "status": "decided", "reversibility": "one_way_door",
            "energy_context": "high",
        }
        check_decision_guard(meta)

    def test_not_decided_ok(self):
        # 还没拍板(open)→ 不校验
        meta = {
            "status": "open", "reversibility": "one_way_door",
            "energy_context": "drain",
        }
        check_decision_guard(meta)


# ---------------- rule ----------------
class TestRule(unittest.TestCase):
    def _base(self, **ov):
        m = {
            "id": "rule-x", "statement": "少依赖", "status": "validated",
            "domain": "work", "source_machine": "work",
        }
        m.update(ov)
        return m

    def test_valid(self):
        validate_rule(self._base())

    def test_bad_status(self):
        with self.assertRaises(ValidationError):
            validate_rule(self._base(status="也许对"))

    def test_missing_statement(self):
        m = self._base()
        del m["statement"]
        with self.assertRaises(ValidationError):
            validate_rule(m)

    def test_evidence_refs_must_be_list(self):
        with self.assertRaises(ValidationError):
            validate_rule(self._base(evidence_refs="log-1"))


# ---------------- fixtures ----------------
class TestFixtures(unittest.TestCase):
    def setUp(self):
        self.vault = Vault(Path(__file__).resolve().parent.parent / "fixtures" / "work")

    def test_planning_fixture(self):
        validate_planning(self.vault.read("plan-2026-q3-01")["meta"])

    def test_decision_fixture(self):
        meta = self.vault.read("dec-2026-0001")["meta"]
        validate_decision(meta)
        check_decision_guard(meta)  # 样例是 two_way_door + high,应放行

    def test_rule_fixture(self):
        validate_rule(self.vault.read("rule-2026-0001")["meta"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
