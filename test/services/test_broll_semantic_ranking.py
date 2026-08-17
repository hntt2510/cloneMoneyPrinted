import unittest
from app.models.project import BrollCandidate, BrollPayload, BrollSemanticIntent, ProjectSpec, VisualCue, VisualType
from app.models.schema import VideoAspect
from app.services.broll import (
    CONCEPT_CLUSTERS,
    _expand_concept_tokens,
    _extract_meaningful_tokens,
    _build_tiered_queries,
    evaluate_semantic_match,
    score_candidate,
)


class TestBrollSemanticRanking(unittest.TestCase):
    def test_concept_clusters_and_expansion(self):
        """Verify synonym clusters properly expand concept tokens."""
        car_tokens = _expand_concept_tokens("vehicle")
        self.assertIn("car", car_tokens)
        self.assertIn("vehicle", car_tokens)
        self.assertIn("automobile", car_tokens)

        tree_tokens = _expand_concept_tokens("tree branch")
        self.assertIn("tree", tree_tokens)
        self.assertIn("branch", tree_tokens)
        self.assertIn("limb", tree_tokens)

        damage_tokens = _expand_concept_tokens("storm damage")
        self.assertIn("damage", damage_tokens)
        self.assertIn("storm", damage_tokens)
        self.assertIn("damaged", damage_tokens)

    def test_tree_branch_uat_hard_acceptance_case(self):
        """Hard Acceptance Case 1: Tree branch falling on parked car during storm.

        Candidate A: Rainy windshield / night traffic (Generic B-roll)
        Candidate B: Parked vehicle damaged by fallen tree branch after storm (Semantic Match)

        Requirement:
        - Candidate A must NOT score HIGH (must score LOW or medium-low with reject keyword penalty).
        - Candidate B MUST score HIGH and significantly outrank Candidate A.
        """
        intent = BrollSemanticIntent(
            subject="parked car",
            action="tree branch falls on",
            object="vehicle",
            setting="outside storm",
            outcome="storm damaged car",
            must_show_concepts=["car", "tree branch", "damage", "storm"],
            preferred_visuals=["fallen tree branch on parked car", "storm damaged vehicle under tree"],
            acceptable_alternatives=["car with branch damage after storm"],
            reject_visuals=["windshield", "wipers", "traffic jam", "highway driving", "blurry", "interior"],
        )

        candidate_a = BrollCandidate(
            id="cand-a-rainy-windshield",
            provider="pexels",
            provider_asset_id="101",
            query="car in rain",
            download_url="https://example.com/a.mp4",
            duration=12.0,
            width=3840,  # Even with 4K resolution!
            height=2160,
            title="Rain drops on car windshield wipers at night",
            description="Bokeh traffic lights through wet blurry windshield",
            tags=["rain", "windshield", "traffic", "night", "wipers", "drive"],
        )

        candidate_b = BrollCandidate(
            id="cand-b-tree-branch-damage",
            provider="pexels",
            provider_asset_id="102",
            query="fallen tree branch on parked car storm",
            download_url="https://example.com/b.mp4",
            duration=10.0,
            width=1920,  # 1080p
            height=1080,
            title="Parked car damaged by heavy fallen tree branch after severe storm",
            description="Large tree limb crushed hood of automobile parked on suburban street during thunderstorm",
            tags=["car", "vehicle", "tree", "branch", "damage", "storm", "crushed", "parked"],
        )

        # Evaluate Candidate A
        score_a, bd_a = score_candidate(
            candidate=candidate_a,
            scene_duration=4.0,
            target_aspect=VideoAspect.landscape,
            semantic_intent=intent,
            query_tier="tier1",
        )
        conf_a = (candidate_a.metadata or {}).get("semantic_confidence")
        rejected_a = (candidate_a.metadata or {}).get("rejected_concepts", [])

        # Evaluate Candidate B
        score_b, bd_b = score_candidate(
            candidate=candidate_b,
            scene_duration=4.0,
            target_aspect=VideoAspect.landscape,
            semantic_intent=intent,
            query_tier="tier1",
        )
        conf_b = (candidate_b.metadata or {}).get("semantic_confidence")
        matched_b = (candidate_b.metadata or {}).get("matched_concepts", [])

        # Assertions
        self.assertEqual(conf_a, "LOW", "Generic blurry windshield must receive LOW confidence")
        self.assertGreater(len(rejected_a), 0, "Candidate A should match reject keywords (windshield/wipers)")
        self.assertEqual(conf_b, "HIGH", "Candidate B must receive HIGH confidence")
        self.assertEqual(len(matched_b), 4, "Candidate B should match all 4 must-show concepts")

        # Candidate B MUST decisively outrank Candidate A
        self.assertGreater(score_b, score_a + 30.0, f"Candidate B ({score_b}) must outrank Candidate A ({score_a}) by > 30 points")
        self.assertGreaterEqual(score_b, 75.0, f"Candidate B score ({score_b}) should be >= 75")
        self.assertLessEqual(score_a, 45.0, f"Candidate A score ({score_a}) should be <= 45")

    def test_side_collision_uat_case(self):
        """Verify side-impact collision outranks generic highway driving."""
        intent = BrollSemanticIntent(
            subject="car",
            action="side impact collision",
            object="vehicle",
            must_show_concepts=["car", "collision"],
            reject_visuals=["highway driving", "commute", "sunny highway"],
        )

        generic_driving = BrollCandidate(
            id="cand-driving",
            provider="pexels",
            provider_asset_id="201",
            query="car driving",
            download_url="https://example.com/drive.mp4",
            duration=8.0,
            width=1920,
            height=1080,
            title="Car driving on highway during morning commute",
            description="Smooth road travel in sedan",
            tags=["car", "driving", "highway", "commute", "travel"],
        )

        collision_video = BrollCandidate(
            id="cand-collision",
            provider="pixabay",
            provider_asset_id="202",
            query="car side impact crash",
            download_url="https://example.com/crash.mp4",
            duration=7.0,
            width=1920,
            height=1080,
            title="Two cars side impact collision at road intersection",
            description="Traffic accident crash vehicle side damage",
            tags=["car", "vehicle", "collision", "crash", "accident", "impact"],
        )

        score_drive, _ = score_candidate(generic_driving, scene_duration=3.0, semantic_intent=intent, query_tier="tier1")
        score_crash, _ = score_candidate(collision_video, scene_duration=3.0, semantic_intent=intent, query_tier="tier1")

        self.assertEqual((generic_driving.metadata or {}).get("semantic_confidence"), "LOW")
        self.assertEqual((collision_video.metadata or {}).get("semantic_confidence"), "HIGH")
        self.assertGreater(score_crash, score_drive + 30.0)

    def test_insurance_paperwork_review_case(self):
        """Verify insurance policy paperwork review outranks generic car driving."""
        intent = BrollSemanticIntent(
            subject="policyholder",
            action="reviewing policy paperwork",
            object="insurance document",
            must_show_concepts=["document", "person"],
            reject_visuals=["highway driving", "traffic", "car"],
        )

        car_video = BrollCandidate(
            id="cand-car",
            provider="pexels",
            provider_asset_id="301",
            query="car",
            download_url="https://example.com/car.mp4",
            duration=10.0,
            width=1920,
            height=1080,
            title="Red car driving fast on highway",
            tags=["car", "speed", "driving", "highway"],
        )

        paperwork_video = BrollCandidate(
            id="cand-paperwork",
            provider="pexels",
            provider_asset_id="302",
            query="reviewing insurance policy paperwork",
            download_url="https://example.com/paper.mp4",
            duration=10.0,
            width=1920,
            height=1080,
            title="Adult person reviewing insurance policy contract paperwork documents at desk",
            description="Close up of policy form reading and signing",
            tags=["person", "document", "paperwork", "policy", "insurance", "contract", "reading"],
        )

        score_car, _ = score_candidate(car_video, scene_duration=3.0, semantic_intent=intent, query_tier="tier1")
        score_paper, _ = score_candidate(paperwork_video, scene_duration=3.0, semantic_intent=intent, query_tier="tier1")

        self.assertEqual((car_video.metadata or {}).get("semantic_confidence"), "LOW")
        self.assertEqual((paperwork_video.metadata or {}).get("semantic_confidence"), "HIGH")
        self.assertGreater(score_paper, score_car + 40.0)

    def test_query_tier_weighting(self):
        """Verify Tier 1 query scores higher than Tier 4 broad fallback for same candidate."""
        candidate = BrollCandidate(
            id="cand-tier-test",
            provider="pexels",
            provider_asset_id="401",
            query="storm damage",
            download_url="https://example.com/storm.mp4",
            duration=8.0,
            width=1920,
            height=1080,
            title="Vehicle storm damage",
            tags=["car", "storm", "damage"],
        )
        intent = BrollSemanticIntent(must_show_concepts=["car", "storm", "damage"])

        score_t1, bd_t1 = score_candidate(candidate, 3.0, semantic_intent=intent, query_tier="tier1")
        score_t4, bd_t4 = score_candidate(candidate, 3.0, semantic_intent=intent, query_tier="tier4")

        self.assertGreater(bd_t1["semantic"], bd_t4["semantic"])
        self.assertGreater(score_t1, score_t4)

    def test_build_tiered_queries_from_payload(self):
        """Verify _build_tiered_queries preserves explicit tiers or assigns fallback order."""
        payload_with_tiers = BrollPayload(
            search_query="fallen tree branch on car",
            query_tiers={
                "tier1": "fallen tree branch on car",
                "tier2": "storm damaged vehicle tree",
                "tier3": "tree limb crushed car",
                "tier4": "car severe storm damage",
            },
        )
        tiered = _build_tiered_queries(payload_with_tiers)
        self.assertEqual(len(tiered), 4)
        self.assertEqual(tiered[0], ("fallen tree branch on car", "tier1"))
        self.assertEqual(tiered[1], ("storm damaged vehicle tree", "tier2"))
        self.assertEqual(tiered[2], ("tree limb crushed car", "tier3"))
        self.assertEqual(tiered[3], ("car severe storm damage", "tier4"))

        # Payload without explicit tiers
        payload_legacy = BrollPayload(
            search_query="car accident",
            fallback_queries=["vehicle collision", "traffic crash"],
        )
        tiered_legacy = _build_tiered_queries(payload_legacy)
        self.assertEqual(tiered_legacy[0], ("car accident", "tier1"))
        self.assertEqual(tiered_legacy[1], ("vehicle collision", "tier2"))
        self.assertEqual(tiered_legacy[2], ("traffic crash", "tier3"))


if __name__ == "__main__":
    unittest.main()
