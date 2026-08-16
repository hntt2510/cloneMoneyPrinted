# Project Specification: Video Research & Asset Builder Pipeline

## 1. Overview
The autonomous video generation pipeline ingests a declarative `project.json` specification, plans multimodal visual cues, acquires and renders assets across multiple modalities, exports professional NLE editing packages, and deterministically synthesizes the final broadcast video.

---

## 2. Stage Execution Order
```
1. Ingestion & Preflight (Fingerprint compute, task workspace binding)
       ↓
2. Visual Planning (LLM/Deterministic visual cues & timeline alignment)
       ↓
3. B-Roll Acquisition (Multi-provider stock candidate search, ranking, and rendering)
       ↓
4. Motion Graphics Render (Remotion TypeScript engine: DATA & TEXT compositions)
       ↓
5. Evidence Acquisition (PyMuPDF PDF extraction, Wikimedia discovery, fallback to TEXT)
       ↓
6. Editor Package Export (Clean video tracks, narration audio, subtitle.srt, edit manifest)
       ↓
7. Final Assembly Engine (Deterministic MoviePy stitching, audio mixing, subtitle burn, QC)
```

---

## 3. Scene Types & Capabilities

| Scene Type | Modality | Engine / Source | Purpose & Payload |
| :--- | :--- | :--- | :--- |
| `DATA` | Dynamic Charts / Numbers | Remotion (React/TypeScript) | Numbers, comparisons, metrics, trends |
| `TEXT` | Kinetic Typography | Remotion (React/TypeScript) | Headlines, callouts, emphasis, key takeaways |
| `BROLL` | Stock & Footage | Pexels, Pixabay, Coverr, Local | Ambient context, narrative pacing |
| `DOCUMENT` | Verified Evidence | PyMuPDF (PDF), Wikimedia | Official reports, contracts, regulatory citations |

### Graceful Degradation & Fallback Invariant
If an optional `DOCUMENT` scene (`evidence_required: false`) cannot find a defensible source meeting the quality threshold (score >= 35.0), the pipeline automatically falls back to a clean `TEXT` kinetic motion scene without failing the pipeline. If `evidence_required: true`, missing evidence halts the pipeline with actionable diagnostics.

---

## 4. Manifests & Provenance Architecture

All artifacts and stages emit immutable, validated JSON manifests:
1. `project_manifest.json`: Top-level project state and artifact pointers.
2. `visual_plan.json`: Planned visual cues and metadata.
3. `timeline.json`: Aligned cue timestamps and narration duration.
4. `broll_manifest.json`: Acquired stock video candidates, trimming ranges, and provider provenance.
5. `motion_manifest.json`: Remotion render specs, component IDs, and output hashes.
6. `evidence_manifest.json`: Verified document bounding boxes, page hints, and publisher trust.
7. `execution_manifest.json`: Comprehensive stage timeline, scene status history, and retry logs.
8. `edit_manifest.json`: NLE-ready manifest mapping clean scene tracks and narration audio.
9. `assembly_manifest.json` / `qc_report.json`: Final synthesized video validation and stream metrics.

---

## 5. Fingerprinting & Idempotency Guarantees
- **Input Fingerprint**: SHA-256 hash over normalized script, timeline cues, visual cues, aspect ratio, fps, and narration config.
- **Stage Ownership**: Workspace bound to input fingerprint; running an incompatible project with the same task ID raises `ProjectRunError` to prevent cross-project cache contamination.
- **Valid Stage Reuse**: Rerunning a previously completed or partially completed task reuses all valid prior outputs (`planning`, `broll`, `motion`, `evidence`, `assembly`) without duplicate computation.
- **Atomic File Operations**: All manifest and render outputs write to temporary nonces and atomically replace destination files (`os.replace`), ensuring crash resilience.

---

## 6. CLI Reference
```bash
# Asset-only execution
python cli.py --project project.json --run-all

# Editor package export
python cli.py --project project.json --run-all --export-editor-package

# End-to-end final assembly
python cli.py --project project.json --run-all --export-editor-package --assemble-final
```
