# Final Video Assembly Engine Specification (G10)

## 1. Overview
The Final Video Assembly Engine deterministically concatenates exported scene video tracks, mixes narration audio with background music (including ducking), optionally burns or muxes subtitles, and performs automated Quality Control (QC) validation.

---

## 2. Directory Layout & Outputs
```
exports/<project_slug>/
├── edit_manifest.json
├── final/
│   ├── final.mp4               # Final assembled broadcast-ready video file
│   ├── assembly_manifest.json  # Fingerprint, config, and assembly metadata
│   └── qc_report.json          # Automated validation report (streams, resolution, duration)
```

---

## 3. `AssemblyConfig` Schema Reference

```json
{
  "fps": 30,
  "resolution": [1920, 1080],
  "aspect_ratio": "16:9",
  "crf": 20,
  "video_codec": "libx264",
  "audio_codec": "aac",
  "audio_bitrate": "192k",
  "audio_mix": {
    "narration_volume": 1.0,
    "bgm_volume": 0.2,
    "ducking_factor": 0.3,
    "ducking_attack": 0.2,
    "ducking_release": 0.5
  },
  "subtitles": {
    "burn_in": false,
    "font_size": 28,
    "font_color": "#ffffff",
    "stroke_color": "#000000",
    "stroke_width": 2
  }
}
```

---

## 4. Automated QC Validation Checks
The assembly pipeline produces `qc_report.json` verifying:
1. `is_valid`: Overall boolean status indicating video passes all inspection checks.
2. `has_video_stream`: Assert video stream is present and decodable.
3. `has_audio_stream`: Assert audio stream is present and non-empty.
4. `resolution`: Matches target resolution (e.g. `[1920, 1080]`).
5. `duration_seconds`: Video duration matches narration / timeline duration within tolerance.
6. `file_size_bytes`: Output file exists on disk with size > 1000 bytes.

---

## 5. CLI Usage
```bash
# Execute full pipeline through final assembly
python cli.py --project project.json --run-all --export-editor-package --assemble-final

# Or run final assembly standalone on an existing edit_manifest.json
python cli.py --assemble-manifest exports/my-project/edit_manifest.json
```
