import unittest
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parents[1] / "SKILL.md"


class SkillContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = SKILL_PATH.read_text(encoding="utf-8")

    def test_stops_without_reviewable_evidence(self):
        self.assertIn("has_reviewable_evidence", self.content)
        self.assertIn("不提问、不评分", self.content)

    def test_objective_focuses_on_strict_daily_understanding_review(self):
        for expected in (
            "extremely strict daily technical reviewer",
            "today's engineering work",
            "underlying mechanisms",
            "reason independently about decisions",
            "Do not reward activity, code volume, commit count",
            "ask follow-up questions instead of immediately",
            "Do not complete missing reasoning",
        ):
            self.assertIn(expected, self.content)

    def test_enforces_one_question_and_bounded_followups(self):
        self.assertIn("每次只问一个问题", self.content)
        self.assertIn("最多追问 2 次", self.content)
        self.assertIn("禁止提前公布分数", self.content)

    def test_uses_fixed_scoring_dimensions(self):
        for expected in (
            "技术理解：40",
            "独立思考：30",
            "推理与表达：15",
            "知识迁移：10",
            "学习闭环：5",
        ):
            self.assertIn(expected, self.content)

    def test_writes_report_without_committing(self):
        self.assertIn('report.current_path', self.content)
        self.assertIn("禁止自动执行 Git 提交", self.content)


if __name__ == "__main__":
    unittest.main()
