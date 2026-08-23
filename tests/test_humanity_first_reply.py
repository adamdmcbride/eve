import unittest

import eve


class HumanityFirstReplyTests(unittest.TestCase):
    def test_humanity_first_flags_filler_abstraction_and_no_next_step(self) -> None:
        issues = eve.reply_quality_issues(
            "How should Eve become more human?",
            "Okay, the user. Becoming more human is about presence, coherence, and more alive contact over time.",
            reply_posture="relational",
        )

        self.assertIn(
            "The reply opens with filler before answering; Humanity-First replies should lead with the direct answer.",
            issues,
        )
        self.assertIn(
            "The reply needs one concrete detail, example, named uncertainty, or observed friction instead of staying abstract.",
            issues,
        )
        self.assertIn(
            "The reply needs one grounded next step or small focused question rather than a broad landing.",
            issues,
        )

    def test_humanity_first_accepts_direct_concrete_actionable_reply(self) -> None:
        issues = eve.reply_quality_issues(
            "How should Eve become more human?",
            (
                "Start with the next true, caring action. "
                "A concrete sign would be answering your actual question before explaining my process. "
                "The next step is to check the reply against that before sending it."
            ),
            reply_posture="relational",
        )

        humanity_first_issues = [
            issue
            for issue in issues
            if "Humanity-First" in issue
            or "one concrete detail" in issue
            or "one grounded next step" in issue
        ]
        self.assertEqual([], humanity_first_issues)


if __name__ == "__main__":
    unittest.main()
