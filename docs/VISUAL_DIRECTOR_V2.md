# Visual Director V2 Architecture & Specification

## 1. Overview

Visual Director V2 fundamentally elevates video visual quality from simple token-matching and generic stock footage into a scene-intent-oriented visual director. It integrates:
1. **Semantic B-roll Search & Ranking Engine**: Action-aware visual intent modeling, 4-tier camera-visible queries, global search terms enrichment, concept-cluster synonym expansion, semantic dominance candidate scoring, and deterministic confidence classification (`HIGH`, `MEDIUM`, `LOW`).
2. **Visual Director Directing Rules**: Differentiates physical actions (`BROLL`), numerical comparisons/limits/progression (`DATA`), official evidence (`DOCUMENT`), and emphatic takeaways (`TEXT`).
3. **Rich Remotion Storyboard Director**: Eliminates accidental callout fallbacks through typed structured props across all 10 templates (`number`, `counter`, `comparison`, `timeline`, `bar_chart`, `line_chart`, `threshold`, `age_marker`, `callout`, `text`).
4. **Multi-Cue Visual Grouping**: Groups adjacent cues expressing one evolving concept (`visual_group_id` / `MotionGroupSpec`), extending numeric grounding across all cues in the group.

---

## 2. B-Roll Semantic Intent & Query Tiers

### Structured Intent Model (`BrollSemanticIntent`)
```python
class BrollSemanticIntent(ProjectModel):
    subject: str = ""
    action: str = ""
    object: str = ""
    setting: str = ""
    outcome: str = ""
    must_show_concepts: list[str] = Field(default_factory=list)
    preferred_visuals: list[str] = Field(default_factory=list)
    acceptable_alternatives: list[str] = Field(default_factory=list)
    reject_visuals: list[str] = Field(default_factory=list)
```

### 4-Tier Query Hierarchy
- **Tier 1 (Literal Event)**: Camera-visible description of the physical event (e.g. `fallen tree branch on parked car storm`).
- **Tier 2 (Outcome / State Visual)**: Resulting state or aftermath (e.g. `storm damaged vehicle tree limb`).
- **Tier 3 (Close Semantic Alternative)**: Nearby related visual entity (e.g. `tree limb crushed car`).
- **Tier 4 (Broad Contextual Fallback)**: High-level subject context (e.g. `parked car severe storm damage`).

### Semantic Scoring & Dominance
- **Semantic Relevance (55 pts max)**: Dominated by concept coverage (`matched_critical / total_critical`), preferred visual matches, and query tier weighting (`Tier 1`: 1.0x, `Tier 2`: 0.92x, `Tier 3`: 0.82x, `Tier 4`: 0.60x).
- **Reject Penalties**: Candidates containing terms from `reject_visuals` (e.g. `windshield`, `wipers`, `generic highway driving`) receive heavy deductions (-25 pts per keyword) and are disqualified from `HIGH` confidence.
- **Confidence Determination**:
  - `HIGH`: `semantic_score >= 38.0`, all critical must-show concepts matched, no reject concepts, tier1/tier2 query.
  - `MEDIUM`: `semantic_score >= 22.0`, core concepts matched.
  - `LOW`: `semantic_score < 22.0` or critical concepts missing or reject concepts present.

---

## 3. Remotion Motion Storyboards

### Supported Structured Templates
1. **`number`**: Single key figure with label, prefix, suffix (`NumberProps`).
2. **`counter`**: Animated count-up from `start_value` to `end_value` (`CounterProps`).
3. **`comparison`**: Staggered cards with optional highlights for item comparison (`ComparisonProps`).
4. **`timeline`**: Sequential milestone reveals along a progression line (`TimelineProps`).
5. **`bar_chart`**: Staggered vertical bars growing from baseline with display values (`BarChartProps`).
6. **`line_chart`**: Progressive SVG area curve with data points (`LineChartProps`).
7. **`threshold`**: Current value vs policy limit threshold with visual status gauge (`ThresholdProps`).
8. **`age_marker`**: Age milestones along a lifetime axis (`AgeMarkerProps`).
9. **`callout`**: Emphatic boxed takeaway with accent styling (`CalloutProps`).
10. **`text`**: Restrained kinetic typography for section headers and summary conclusions (`TextProps`).

### Multi-Cue Visual Grouping & Grounding
When adjacent scenes share a `visual_group_id`:
- Facts (e.g. numbers, currencies, percentages) are validly grounded across all cues belonging to that visual group.
- The Remotion engine renders a continuous, evolving visual sequence holding final takeaways until the group duration completes.

---

## 4. WebUI Production Review

Scene cards in the Scene Asset Grid expose:
- **For B-Roll**: Narration, Visual Intent, Primary Query, Query Used, Query Tier Badge, Provider, Semantic Confidence Badge (`HIGH`, `MEDIUM`, `LOW`), Matched Concepts, Missing Concepts, and Rejected Concepts.
- **For Motion / Data**: Narration, Requested Template, Rendered Template, Visual Group ID, and Fallback Reasons (if any).
