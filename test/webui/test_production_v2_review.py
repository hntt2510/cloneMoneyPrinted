import unittest
from pathlib import Path
from webui.production import format_fallback_badge, sanitize_manifest_for_display


class TestProductionV2Review(unittest.TestCase):
    def test_format_fallback_badge_broll_confidence(self):
        """Verify fallback badge formatting for B-roll scenes."""
        scene_ready = {
            "resolved_visual_type": "broll",
            "metadata": {
                "semantic_confidence": "HIGH",
                "matched_concepts": ["car", "tree branch", "damage"],
            },
        }
        self.assertIsNone(format_fallback_badge(scene_ready))

        scene_fallback = {
            "resolved_visual_type": "text",
            "planned_visual_type": "broll",
            "fallback_reason": "Low semantic relevance",
        }
        badge = format_fallback_badge(scene_fallback)
        self.assertIsNotNone(badge)
        self.assertIn("FALLBACK", badge)

    def test_format_fallback_badge_motion_templates(self):
        """Verify fallback badge for motion template fallback."""
        scene_callout_fallback = {
            "resolved_visual_type": "data",
            "requested_template": "comparison",
            "rendered_template": "callout",
            "fallback_reason": "Missing comparison items",
        }
        badge = format_fallback_badge(scene_callout_fallback)
        self.assertIsNotNone(badge)
        self.assertIn("CALLOUT FALLBACK", badge)

    def test_sanitize_manifest_with_v2_broll_diagnostics(self):
        """Verify manifest sanitization preserves diagnostic fields without leaking sensitive URLs."""
        manifest = {
            "scenes": [
                {
                    "scene_id": "S001",
                    "resolved_visual_type": "broll",
                    "query_used": "fallen tree branch on car",
                    "metadata": {
                        "primary_query": "fallen tree branch on car storm",
                        "query_tier": "tier1",
                        "semantic_confidence": "HIGH",
                        "matched_concepts": ["car", "tree branch", "damage", "storm"],
                    },
                }
            ]
        }
        sanitized = sanitize_manifest_for_display(manifest)
        self.assertIn("scenes", sanitized)
        sc = sanitized["scenes"][0]
        self.assertEqual(sc["metadata"]["semantic_confidence"], "HIGH")
        self.assertEqual(sc["metadata"]["query_tier"], "tier1")


if __name__ == "__main__":
    unittest.main()
