import unittest

import eve_capability_intelligence as intelligence


def component(
    component_id,
    package,
    repository,
    installed,
    *,
    mode="installed_version",
):
    return {
        "id": component_id,
        "name": component_id,
        "kind": "python_package" if component_id != "mcporter" else "npm_package",
        "package": package,
        "release_repository": repository,
        "release_feature_mode": mode,
        "local_version": installed,
        "adoption": "Run the isolated component canary.",
    }


def feed(repository, tag, *, prerelease=False):
    return {
        "repository": repository,
        "releases": [
            {
                "tag": tag,
                "name": tag,
                "published_at": "2026-08-23T00:00:00Z",
                "url": f"https://github.com/{repository}/releases/tag/{tag}",
                "prerelease": prerelease,
                "feature_bullets": ["Fix package behavior."],
            }
        ],
    }


class CapabilityReleaseMatchingTests(unittest.TestCase):
    def test_different_monorepo_package_tag_is_not_python_update_candidate(self):
        subsystems = {
            "eve": {
                "components": [
                    component(
                        "deepeval-eve-runtime",
                        "deepeval",
                        "confident-ai/deepeval",
                        "4.1.10",
                    )
                ]
            }
        }

        reviews = intelligence.build_feature_reviews(
            subsystems,
            [feed("confident-ai/deepeval", "typescript-v0.9.11")],
            checked_at="2026-08-23T00:00:00+00:00",
        )

        self.assertEqual(1, len(reviews))
        self.assertEqual("research_only", reviews[0]["state"])
        self.assertFalse(reviews[0]["tag_track"]["compatible"])
        self.assertEqual("different_monorepo_package_track", reviews[0]["tag_track"]["reason"])

    def test_older_release_head_is_not_offered_as_update(self):
        subsystems = {
            "eve": {
                "components": [
                    component("mcporter", "mcporter", "openclaw/mcporter", "0.13.7")
                ]
            }
        }

        reviews = intelligence.build_feature_reviews(
            subsystems,
            [feed("openclaw/mcporter", "v0.13.6")],
            checked_at="2026-08-23T00:00:00+00:00",
        )

        self.assertEqual("historical", reviews[0]["state"])
        self.assertIn("older than", reviews[0]["classification_reason"])

    def test_newer_direct_package_tag_remains_candidate(self):
        subsystems = {
            "eve": {
                "components": [
                    component(
                        "deepeval-eve-runtime",
                        "deepeval",
                        "confident-ai/deepeval",
                        "4.1.10",
                    )
                ]
            }
        }

        reviews = intelligence.build_feature_reviews(
            subsystems,
            [feed("confident-ai/deepeval", "v4.2.0")],
            checked_at="2026-08-23T00:00:00+00:00",
        )

        self.assertEqual("candidate", reviews[0]["state"])
        self.assertTrue(reviews[0]["tag_track"]["compatible"])
        self.assertEqual("4.2.0", reviews[0]["tag_track"]["version"])

    def test_newer_direct_lab_package_tag_remains_lab_candidate(self):
        subsystems = {
            "eve": {
                "components": [
                    component(
                        "ragas-eve-runtime",
                        "ragas",
                        "explodinggradients/ragas",
                        "0.3.2",
                        mode="lab_only",
                    )
                ]
            }
        }

        reviews = intelligence.build_feature_reviews(
            subsystems,
            [feed("explodinggradients/ragas", "v0.4.3")],
            checked_at="2026-08-23T00:00:00+00:00",
        )

        self.assertEqual("lab_candidate", reviews[0]["state"])


if __name__ == "__main__":
    unittest.main()
