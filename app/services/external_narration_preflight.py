from __future__ import annotations

import enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.services.timeline import (
    TimelineError,
    parse_srt_file,
    validate_script_srt_alignment,
)
from app.services import voice


class TimingQuality(str, enum.Enum):
    GOOD = "GOOD"
    COARSE = "COARSE"
    INVALID = "INVALID"


class ExternalNarrationPreflightResult(BaseModel):
    audio_duration_seconds: float = 0.0
    srt_start_seconds: float = 0.0
    srt_end_seconds: float = 0.0
    srt_duration_seconds: float = 0.0
    cue_count: int = 0
    duration_delta_seconds: float = 0.0
    text_alignment_confidence: float | None = None
    timing_quality: TimingQuality = TimingQuality.INVALID
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    is_valid: bool = False


def preflight_external_narration(
    audio_path: str | Path,
    srt_path: str | Path,
    script: str | None = None,
    tolerance_seconds: float = 0.5,
) -> ExternalNarrationPreflightResult:
    """Canonical preflight validation for external audio + SRT timing contract.

    Enforces:
    1. Real media duration bounds.
    2. SRT syntax, monotonicity, and non-overlapping cue boundaries.
    3. Tight temporal alignment between audio duration and SRT end (overrun and underrun).
    4. Granularity / coarseness detection (rejecting single-cue long narration for synchronized kinetic production).
    5. Textual alignment matching between SRT cue text and canonical script.
    """
    result = ExternalNarrationPreflightResult()
    audio_p = Path(audio_path).expanduser().resolve() if audio_path else None
    srt_p = Path(srt_path).expanduser().resolve() if srt_path else None

    # 1. Validate Audio File
    if not audio_p or not audio_p.exists() or not audio_p.is_file():
        result.errors.append(f"External narration audio file not found: {audio_path}")
        result.timing_quality = TimingQuality.INVALID
        result.is_valid = False
        return result

    try:
        audio_duration = float(voice.get_audio_duration(str(audio_p)) or 0.0)
    except Exception as exc:
        result.errors.append(f"Failed to read audio duration: {exc}")
        result.timing_quality = TimingQuality.INVALID
        result.is_valid = False
        return result

    if audio_duration <= 0.0:
        result.errors.append("External narration audio has zero or invalid duration.")
        result.timing_quality = TimingQuality.INVALID
        result.is_valid = False
        return result

    result.audio_duration_seconds = round(audio_duration, 3)

    # 2. Validate SRT File
    if not srt_p or not srt_p.exists() or not srt_p.is_file():
        result.errors.append(f"External narration timing file not found: {srt_path}")
        result.timing_quality = TimingQuality.INVALID
        result.is_valid = False
        return result

    try:
        cues = parse_srt_file(srt_p)
    except TimelineError as te:
        result.errors.append(f"Invalid SRT timing file: {te}")
        result.timing_quality = TimingQuality.INVALID
        result.is_valid = False
        return result
    except Exception as exc:
        result.errors.append(f"Failed to read SRT timing file: {exc}")
        result.timing_quality = TimingQuality.INVALID
        result.is_valid = False
        return result

    if not cues:
        result.errors.append("SRT contains no usable cues")
        result.timing_quality = TimingQuality.INVALID
        result.is_valid = False
        return result

    result.cue_count = len(cues)
    result.srt_start_seconds = round(cues[0].start, 3)
    result.srt_end_seconds = round(cues[-1].end, 3)
    result.srt_duration_seconds = round(cues[-1].end - cues[0].start, 3)
    delta = cues[-1].end - audio_duration
    result.duration_delta_seconds = round(delta, 3)

    # 3. Validate Individual Cues & Monotonic Bounds
    previous_end = 0.0
    for idx, cue in enumerate(cues):
        if cue.start < 0 or cue.end <= cue.start:
            result.errors.append(
                f"SRT cue {idx + 1} has invalid time interval: {cue.start:.3f}s -> {cue.end:.3f}s"
            )
        if cue.start < previous_end:
            result.errors.append(
                f"SRT cue {idx + 1} ({cue.start:.3f}s) overlaps with previous cue ({previous_end:.3f}s)"
            )
        if cue.start > audio_duration + tolerance_seconds:
            result.errors.append(
                f"SRT cue {idx + 1} starts at {cue.start:.3f}s which exceeds audio duration {audio_duration:.3f}s (tolerance {tolerance_seconds}s)"
            )
        if cue.end > audio_duration + tolerance_seconds:
            result.errors.append(
                f"SRT cue {idx + 1} ends at {cue.end:.3f}s which exceeds audio duration {audio_duration:.3f}s (tolerance {tolerance_seconds}s)"
            )
        previous_end = max(previous_end, cue.end)

    # 4. Overall Audio <-> SRT Temporal Overrun / Underrun Check
    if delta > tolerance_seconds:
        result.errors.append(
            f"External narration timing mismatch:\n"
            f"Audio duration: {audio_duration:.2f}s\n"
            f"SRT final timestamp: {result.srt_end_seconds:.2f}s\n"
            f"Difference: {delta:+.2f}s\n"
            f"The uploaded SRT appears to belong to different audio or contains incorrect timestamps."
        )
    elif delta < -tolerance_seconds:
        result.errors.append(
            f"External narration timing underrun:\n"
            f"Audio duration: {audio_duration:.2f}s\n"
            f"SRT final timestamp: {result.srt_end_seconds:.2f}s\n"
            f"Difference: {delta:+.2f}s\n"
            f"{abs(delta):.2f}s of audio is uncovered by subtitles."
        )

    # 5. Granularity / Coarseness Validation
    if not result.errors:
        # If narration is longer than 30s but only 1 cue exists
        if len(cues) == 1 and audio_duration > 30.0:
            result.timing_quality = TimingQuality.COARSE
            result.errors.append(
                f"SRT timing is too coarse for synchronized production: "
                f"1 cue covers {audio_duration:.1f} seconds. "
                f"Please provide a subtitle SRT with sentence/phrase-level timestamps."
            )
        elif len(cues) < 2 and audio_duration > 30.0:
            result.timing_quality = TimingQuality.COARSE
            result.errors.append(
                f"SRT timing is too coarse for synchronized production: "
                f"{len(cues)} cues cover {audio_duration:.1f} seconds."
            )
        else:
            # Check for any individual outlier cue that spans > 35s in multi-cue SRT
            long_cues = [c for c in cues if (c.end - c.start) > 35.0]
            if long_cues:
                result.warnings.append(
                    f"SRT contains {len(long_cues)} long cue(s) spanning > 35s; intra-cue timing within these cues will be estimated."
                )

    # 6. Textual Alignment Validation (if script is provided)
    if script and script.strip() and not result.errors:
        try:
            confidence = validate_script_srt_alignment(cues, script)
            result.text_alignment_confidence = round(confidence, 3)
        except TimelineError as te:
            result.errors.append(str(te))
        except Exception as exc:
            result.errors.append(f"Text alignment validation failed: {exc}")

    # 7. Final Status Determination
    if result.errors:
        if result.timing_quality != TimingQuality.COARSE:
            result.timing_quality = TimingQuality.INVALID
        result.is_valid = False
    else:
        result.timing_quality = TimingQuality.GOOD
        result.is_valid = True

    return result
