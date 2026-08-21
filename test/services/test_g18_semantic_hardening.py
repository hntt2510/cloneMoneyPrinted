from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.motion import (
    SemanticDataIntent,
    VisualGrammar,
)
from app.models.project import (
    BrollPayload,
    DataPayload,
    DataTemplate,
    ProjectSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.broll import (
    MIN_BROLL_CONFIDENCE_SCORE,
    BrollAcquisitionError,
    BrollCandidate,
    BrollSelectionContext,
    StockSearchResult,
    acquire_broll_scene,
    score_candidate,
)
from app.services.data_visualization_director import (
    DataVisualizationDirector,
    extract_grounded_comparison_entities,
    extract_grounded_entity_definition,
)
from app.services.visual_planner import _apply_diversity, classify_narration


def _create_mock_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x1cftypisom\x00\x00\x02\x00isomiso2mp41")
    return path


class TestG18SemanticHardening(unittest.TestCase):
    """Unit and regression tests for G18.2:
    1. Generic qualitative comparison without domain hardcoding (Renting vs Buying)
    2. Incomplete comparison without invented definitions (Option A vs Option B)
    3. Grounded insurance comparison (dynamically extracted, zero hardcoded strings)
    4. 4-cue breakdown grouping and deduplication ($6k, $1k, $1k, $5k)
    5. Hard B-roll progression (weak Tier 1/2 skipped without download, strong candidate chosen)
    6. All-weak B-roll fallback (all candidates < floor -> safe acquisition rejection)
    """

    def test_generic_qualitative_comparison_zero_domain_leakage(self) -> None:
        """Section 4: Test Renting vs Buying generic comparison.
        Must have:
          RENTING: Temporary use
          BUYING: Ownership
        Must NOT contain:
          PREMIUM, DEDUCTIBLE, insurance, coverage, claim
        """
        cues = [
            TimelineCue(id="C001", order=1, start=0.0, end=3.0, narration="Renting is different from buying."),
            TimelineCue(id="C002", order=2, start=3.0, end=6.0, narration="Renting gives temporary use."),
            TimelineCue(id="C003", order=3, start=6.0, end=9.0, narration="Buying gives ownership."),
        ]

        decisions = [
            VisualCue(id="C001", order=1, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=0.0, end=3.0, narration=cues[0].narration, payload={"search_query": "apartment house"}),
            VisualCue(id="C002", order=2, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=3.0, end=6.0, narration=cues[1].narration, payload={"search_query": "rental agreement"}),
            VisualCue(id="C003", order=3, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=6.0, end=9.0, narration=cues[2].narration, payload={"search_query": "keys deed"}),
        ]

        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Real Estate Comparison", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "renting vs buying", "script": "Renting is different from buying."},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        adapted = _apply_diversity(project, cues, decisions)

        # All 3 cues must receive the same visual_group_id and comparison template
        gid = adapted[0].visual_group_id
        self.assertIsNotNone(gid)
        self.assertEqual(adapted[1].visual_group_id, gid)
        self.assertEqual(adapted[2].visual_group_id, gid)

        for c in adapted:
            self.assertEqual(c.visual_type, VisualType.data)
            self.assertEqual(c.payload.get("template"), "comparison")
            items = c.payload.get("data", {}).get("items", [])
            self.assertEqual(len(items), 2)

            labels = [it["label"].upper() for it in items]
            values = [str(it["value"]) for it in items]

            self.assertIn("RENTING", labels)
            self.assertIn("BUYING", labels)

            # Check that definition values are grounded in narration
            combined_values = " ".join(values).lower()
            self.assertTrue("temporary use" in combined_values or "gives temporary use" in combined_values)
            self.assertTrue("ownership" in combined_values or "gives ownership" in combined_values)

            # Crucial: verify ZERO insurance domain leakage
            for forbidden in ["PREMIUM", "DEDUCTIBLE", "INSURANCE", "COVERAGE", "CLAIM"]:
                self.assertNotIn(forbidden, " ".join(labels))
                self.assertNotIn(forbidden.lower(), combined_values)

    def test_incomplete_comparison_fallback_no_invented_descriptions(self) -> None:
        """Section 5: Incomplete comparison ('Option A is different from Option B.')
        without subsequent definition cues must NOT invent descriptions.
        """
        narration = "Option A is different from Option B."
        ents = extract_grounded_comparison_entities(narration)
        self.assertIsNotNone(ents)
        e1, e2 = ents
        self.assertEqual(e1.upper(), "OPTION A")
        self.assertEqual(e2.upper(), "OPTION B")

        director = DataVisualizationDirector()
        spec = director.direct_visual_specification(narration=narration, headline="OPTION A VS OPTION B")
        self.assertEqual(spec.grammar, VisualGrammar.comparison)

        items = spec.props.get("items", [])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["label"], "OPTION A")
        self.assertEqual(items[1]["label"], "OPTION B")

        # Must not invent long fabricated explanations
        self.assertNotIn("ongoing cost", str(items[0].get("value", "")).lower())
        self.assertNotIn("covered claim", str(items[1].get("value", "")).lower())
        self.assertNotIn("insurance", str(items[0].get("value", "")).lower())

    def test_insurance_qualitative_comparison_grounded_dynamically(self) -> None:
        """Section 14: Premium vs Deductible must render with grounded definitions
        derived from narration text, NOT from hardcoded domain defaults.
        """
        cues = [
            TimelineCue(id="C007", order=7, start=20.0, end=23.4, narration="That deductible is very different from your insurance premium."),
            TimelineCue(id="C008", order=8, start=23.4, end=27.2, narration="Your premium is the ongoing cost you pay to maintain the policy,"),
            TimelineCue(id="C009", order=9, start=27.2, end=32.2, narration="Your deductible is your share of the cost when you actually make a covered claim."),
        ]
        decisions = [
            VisualCue(id="C007", order=7, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=20.0, end=23.4, narration=cues[0].narration, payload={"search_query": "insurance policy"}),
            VisualCue(id="C008", order=8, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=23.4, end=27.2, narration=cues[1].narration, payload={"search_query": "monthly payment"}),
            VisualCue(id="C009", order=9, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=27.2, end=32.2, narration=cues[2].narration, payload={"search_query": "car claim"}),
        ]
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Insurance 60s Breakdown", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "auto insurance collision deductible", "script": "test script"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        adapted = _apply_diversity(project, cues, decisions)
        gid = adapted[0].visual_group_id
        self.assertIsNotNone(gid)
        self.assertEqual(adapted[1].visual_group_id, gid)
        self.assertEqual(adapted[2].visual_group_id, gid)

        items = adapted[0].payload.get("data", {}).get("items", [])
        self.assertEqual(len(items), 2)
        labels = [it["label"] for it in items]
        self.assertIn("PREMIUM", labels)
        self.assertIn("DEDUCTIBLE", labels)

        # Grounded definitions
        prem_item = next(it for it in items if it["label"] == "PREMIUM")
        ded_item = next(it for it in items if it["label"] == "DEDUCTIBLE")
        self.assertIn("ongoing cost", prem_item["value"].lower())
        self.assertIn("share of the cost", ded_item["value"].lower())

    def test_four_cue_breakdown_deduplication_preserved(self) -> None:
        """Section 13: 4-cue repair breakdown sequence ($6k, $1k, $1k, $5k)
        must preserve single BreakdownGroupMaster and 1000 + 5000 == 6000 arithmetic.
        """
        cues = [
            TimelineCue(id="C001", order=1, start=0.0, end=2.0, narration="Let's use a simple example."),
            TimelineCue(id="C002", order=2, start=2.0, end=5.8, narration="Suppose repairing your car costs six thousand dollars."),
            TimelineCue(id="C003", order=3, start=5.8, end=8.9, narration="Your collision deductible is one thousand dollars."),
            TimelineCue(id="C004", order=4, start=8.9, end=14.2, narration="You would generally be responsible for the first one thousand dollars,"),
            TimelineCue(id="C005", order=5, start=14.2, end=17.7, narration="while the insurance company could cover the remaining five thousand dollars,"),
        ]
        decisions = [
            VisualCue(id="C001", order=1, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=0.0, end=2.0, narration=cues[0].narration, payload={"search_query": "car accident"}),
            VisualCue(id="C002", order=2, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=2.0, end=5.8, narration=cues[1].narration, payload={"template": "number", "headline": "REPAIR COST"}),
            VisualCue(id="C003", order=3, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=5.8, end=8.9, narration=cues[2].narration, payload={"template": "number", "headline": "DEDUCTIBLE"}),
            VisualCue(id="C004", order=4, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=8.9, end=14.2, narration=cues[3].narration, payload={"template": "number", "headline": "YOU PAY"}),
            VisualCue(id="C005", order=5, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=14.2, end=17.7, narration=cues[4].narration, payload={"template": "number", "headline": "INSURANCE"}),
        ]
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Insurance 60s Breakdown", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "auto insurance collision deductible", "script": "test script"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        adapted = _apply_diversity(project, cues, decisions)
        gid = adapted[1].visual_group_id
        for idx in range(1, 5):
            self.assertEqual(adapted[idx].visual_group_id, gid)
            self.assertEqual(adapted[idx].payload.get("template"), "breakdown")
            total_val = adapted[idx].payload.get("data", {}).get("total", {}).get("numeric_value")
            parts = adapted[idx].payload.get("data", {}).get("parts", [])
            self.assertEqual(total_val, 6000.0)
            self.assertEqual(len(parts), 2)
            self.assertEqual(parts[0]["numeric_value"] + parts[1]["numeric_value"], total_val)

    def test_two_cue_threshold_sequence_grouping(self) -> None:
        """Validate that a 2-cue threshold sequence ($25k coverage limit vs $40k damage)
        is automatically grouped and adapted into threshold data templates without domain hardcoding.
        """
        cues = [
            TimelineCue(id="C037", order=37, start=128.8, end=133.8, narration="Imagine you have twenty-five thousand dollars of property damage liability coverage,"),
            TimelineCue(id="C038", order=38, start=133.8, end=137.5, narration="but you cause forty thousand dollars in covered damage."),
        ]
        decisions = [
            VisualCue(id="C037", order=37, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=128.8, end=133.8, narration=cues[0].narration, payload={"template": "number", "headline": "COVERAGE"}),
            VisualCue(id="C038", order=38, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=133.8, end=137.5, narration=cues[1].narration, payload={"template": "number", "headline": "DAMAGE"}),
        ]
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Threshold Test", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "coverage limits", "script": "test"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        adapted = _apply_diversity(project, cues, decisions)
        self.assertIsNotNone(adapted[0].visual_group_id)
        self.assertEqual(adapted[0].visual_group_id, adapted[1].visual_group_id)
        for c in adapted:
            self.assertEqual(c.visual_type, VisualType.data)
            self.assertEqual(c.payload.get("template"), "threshold")
            self.assertEqual(c.payload.get("data", {}).get("threshold_value"), 25000.0)
            self.assertEqual(c.payload.get("data", {}).get("current_value"), 40000.0)


    def test_hard_broll_progression_skips_weak_candidates_and_selects_strong(self) -> None:
        """Section 10: Mock:
        - Tier 1 candidate: weak score (< 35.0, irrelevant metadata)
        - Tier 2 candidate: weak score (< 35.0)
        - Provider 2 (or Tier 3) candidate: strong semantic candidate (score >= 80.0)
        Expected: Weak candidates are NOT downloaded, strong candidate is downloaded and selected.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)
            synthetic_source = _create_mock_video(task_dir / "valid_source.mp4")

            project = ProjectSpec.model_validate({
                "schema_version": "1.0",
                "project": {"title": "Test B-roll Progression", "aspect_ratio": "16:9", "fps": 30},
                "script": {"subject": "storm damage", "script": "car storm"},
                "narration": {"mode": "tts"},
                "production": {"video_source": "pexels"},
            })

            cue = VisualCue(
                id="S011",
                order=11,
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                narration="Your car is parked outside during a storm.",
                start=0.0,
                end=4.0,
                payload=BrollPayload(
                    search_query="car parked storm",
                    fallback_queries=["storm weather car", "storm clouds heavy rain"],
                    avoid=["interior", "bokeh", "blurry"],
                    source_priority=["pexels", "pixabay", "coverr"],
                    query_tiers={
                        "tier1": "car parked storm",
                        "tier2": "storm weather car",
                        "tier3": "storm clouds heavy rain",
                    },
                ).model_dump(mode="json"),
            )

            # Tier 1 candidate: completely unrelated metadata (e.g. coffee mug), score < 35
            weak_tier1 = BrollCandidate(
                id="pex-weak-t1",
                provider="pexels",
                provider_asset_id="w1",
                query="car parked storm",
                title="Coffee mug on breakfast table",
                tags=["coffee", "mug", "breakfast", "morning"],
                download_url="https://example.com/w1.mp4",
                duration=10.0,
                width=1920,
                height=1080,
            )

            # Tier 2 candidate: completely unrelated metadata (e.g. dancing in studio), score < 35
            weak_tier2 = BrollCandidate(
                id="pex-weak-t2",
                provider="pexels",
                provider_asset_id="w2",
                query="storm weather car",
                title="Studio dancer hip hop training",
                tags=["dancer", "studio", "hip hop", "music"],
                download_url="https://example.com/w2.mp4",
                duration=10.0,
                width=1920,
                height=1080,
            )

            # Tier 3 (or Pixabay): strong match for storm rain
            strong_cand = BrollCandidate(
                id="pix-strong-t3",
                provider="pixabay",
                provider_asset_id="s1",
                query="storm clouds heavy rain",
                title="Dramatic storm clouds and heavy rain pouring",
                tags=["storm", "clouds", "heavy", "rain", "weather"],
                download_url="https://example.com/strong.mp4",
                duration=8.0,
                width=1920,
                height=1080,
            )

            def mock_search(provider, query, **kwargs):
                if query == "car parked storm" and provider == "pexels":
                    return StockSearchResult(provider="pexels", query=query, candidates=[weak_tier1])
                if query == "storm weather car" and provider == "pexels":
                    return StockSearchResult(provider="pexels", query=query, candidates=[weak_tier2])
                if query == "storm clouds heavy rain" and provider == "pixabay":
                    return StockSearchResult(provider="pixabay", query=query, candidates=[strong_cand])
                return StockSearchResult(provider=provider, query=query, candidates=[])

            downloaded_ids: list[str] = []

            def mock_download(candidate, dest_path):
                downloaded_ids.append(candidate.id)
                shutil.copyfile(synthetic_source, dest_path)
                return Path(dest_path)

            ctx = BrollSelectionContext()
            with patch("app.services.broll.search_stock_candidates_detailed", side_effect=mock_search), \
                 patch("app.services.broll.download_candidate", side_effect=mock_download), \
                 patch("app.services.broll.render_scene_clip", return_value=(8.0, 0.0, 4.0)):
                asset = acquire_broll_scene(cue, project, task_dir, ctx)

            # Assert: Weak candidates were NOT downloaded!
            self.assertNotIn("pex-weak-t1", downloaded_ids)
            self.assertNotIn("pex-weak-t2", downloaded_ids)

            # Assert: Strong candidate was downloaded and selected
            self.assertEqual(downloaded_ids, ["pix-strong-t3"])
            self.assertEqual(asset.candidate_id, "pix-strong-t3")
            self.assertEqual(asset.provider, "pixabay")

    def test_all_weak_broll_triggers_safe_acquisition_error(self) -> None:
        """Section 11: When all providers/tiers return only weak candidates (score < 35.0),
        acquisition must refuse to silently accept weak footage and raise BrollAcquisitionError.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)

            project = ProjectSpec.model_validate({
                "schema_version": "1.0",
                "project": {"title": "Test Fallback", "aspect_ratio": "16:9", "fps": 30},
                "script": {"subject": "test", "script": "test"},
                "narration": {"mode": "tts"},
                "production": {"video_source": "pexels"},
            })

            cue = VisualCue(
                id="S014",
                order=14,
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                narration="Animal damage or falling objects.",
                start=0.0,
                end=4.0,
                payload=BrollPayload(
                    search_query="animal damage falling objects",
                    avoid=["text overlay", "bokeh"],
                    source_priority=["pexels", "pixabay"],
                ).model_dump(mode="json"),
            )

            # Only weak candidates that score < 35
            weak_c = BrollCandidate(
                id="weak-cand-1",
                provider="pexels",
                provider_asset_id="w1",
                query="animal damage falling objects",
                title="Generic abstract background blur",
                tags=["abstract", "blur", "bokeh", "gradient"],
                download_url="https://example.com/weak.mp4",
                duration=5.0,
                width=1920,
                height=1080,
            )

            def mock_search(provider, query, **kwargs):
                return StockSearchResult(provider=provider, query=query, candidates=[weak_c])

            ctx = BrollSelectionContext()
            with patch("app.services.broll.search_stock_candidates_detailed", side_effect=mock_search):
                with self.assertRaises(BrollAcquisitionError):
                    acquire_broll_scene(cue, project, task_dir, ctx)


if __name__ == "__main__":
    unittest.main()
