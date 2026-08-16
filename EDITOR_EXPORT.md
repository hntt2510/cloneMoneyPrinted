# Editor-Ready Export Package Specification (G09)

## 1. Overview
The Editor-Ready Export Package transforms rendered scene assets, continuous audio, and subtitle streams into a structured directory ready for import into professional Non-Linear Editors (NLEs) such as **Adobe Premiere Pro**, **DaVinci Resolve**, **CapCut**, and **Final Cut Pro**.

---

## 2. Directory Layout
```
exports/<project_slug>/
├── edit_manifest.json          # Complete JSON specification of timeline & scene assets
├── README_EDIT.md              # Human-readable assembly instructions and scene breakdown
├── project.json                # Original input specification
├── project.executed.json       # Final resolved execution specification
├── execution_manifest.json     # Pipeline run trace and stage logs
├── narration/
│   ├── narration.wav / .mp3    # Continuous narration master audio track
│   └── subtitle.srt            # Timecode-aligned subtitle track
├── scenes/
│   ├── S001_DATA.mp4           # Clean, silent visual video track (frame-exact duration)
│   ├── S002_TEXT.mp4
│   ├── S003_BROLL.mp4
│   └── S004_DOCUMENT.mp4
└── sources/
    └── source_manifest.json    # Full provenance and licensing metadata
```

---

## 3. Core Invariants
1. **Silent Clean Video Tracks**: All MP4 files in `scenes/` are completely silent, allowing editors full control over audio mixdown.
2. **Exact Frame Boundaries**: Each scene is rendered and trimmed to the exact integer frame count computed from `fps * duration`.
3. **Deterministic Provenance**: Every scene entry records source IDs, stock provider candidate IDs, document page numbers, and SHA-256 hashes.
4. **No Premature Assembly**: Export packages do not create `final.mp4` by default unless explicitly invoked with `--assemble-final`.

---

## 4. `edit_manifest.json` Schema Reference

```json
{
  "schema_version": "1.0",
  "project_title": "Retirement Planning Guide",
  "project_slug": "retirement-planning-guide",
  "task_id": "task-001",
  "source_project_fingerprint": "a1b2c3d4...",
  "export_fingerprint": "e5f6g7h8...",
  "package_status": "complete",
  "fps": 30,
  "resolution": [1920, 1080],
  "aspect_ratio": "16:9",
  "duration_frames": 180,
  "duration_seconds": 6.0,
  "narration_file": "narration/narration.wav",
  "narration_sha256": "narr_hash...",
  "subtitle_file": "narration/subtitle.srt",
  "subtitle_sha256": "sub_hash...",
  "scenes": [
    {
      "scene_id": "S001",
      "order": 1,
      "planned_visual_type": "data",
      "resolved_visual_type": "data",
      "start_frame": 0,
      "end_frame": 60,
      "duration_frames": 60,
      "exported_file": "scenes/S001_DATA.mp4",
      "sha256": "scene_hash...",
      "provenance_reference": {}
    }
  ]
}
```

---

## 5. NLE Timeline Assembly Guide
1. Create a new sequence matching the project resolution (e.g. 1920x1080) and frame rate (30fps).
2. Place all video files from `scenes/` sequentially on **Video Track 1** in numerical order (`S001`, `S002`, ...).
3. Place `narration/narration.<ext>` on **Audio Track 1** aligned to timeline start (`00:00:00:00`).
4. Import `narration/subtitle.srt` onto the **Subtitle Track**.
