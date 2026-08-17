from __future__ import annotations

import difflib
import logging
import re
import shutil
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Literal

from app.models.project import TimelineCue, TimelinePlan
from app.services import subtitle, voice

logger = logging.getLogger(__name__)

MIN_BEAT_SECONDS = 1.75
TARGET_BEAT_SECONDS = 4.0
SOFT_MAX_BEAT_SECONDS = 6.5
# Tolerance for SRT/encoder rounding at audio boundary (seconds)
AUDIO_DURATION_TOLERANCE = 0.5
# Minimum ratio of matched tokens required for high-confidence alignment
ALIGNMENT_CONFIDENCE_THRESHOLD = 0.35

_TIMESTAMP_RE = re.compile(
    r"(?P<h>[0-9]+):(?P<m>[0-5][0-9]):(?P<s>[0-5][0-9])[,\.](?P<ms>[0-9]{3})"
)
_CLAUSE_RE = re.compile(r"(?<=[.!?;:,])\s+|\s+(?=—|–|-\s)")


class TimelineError(ValueError):
    """Invalid or unusable narration timing data."""


@dataclass(frozen=True)
class SrtCue:
    start: float
    end: float
    text: str


def _parse_timestamp(value: str) -> float:
    match = _TIMESTAMP_RE.fullmatch(value.strip())
    if not match:
        raise TimelineError(f"invalid SRT timestamp: {value!r}")
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms")) / 1000
    )


def _format_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_part, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{millis:03d}"


def parse_srt_text(content: str) -> list[SrtCue]:
    cues: list[SrtCue] = []
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    previous_end = 0.0
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines()]
        timing_index = next(
            (index for index, line in enumerate(lines) if "-->" in line), None
        )
        if timing_index is None:
            continue
        timing = lines[timing_index].split("-->", 1)
        if len(timing) != 2:
            raise TimelineError("invalid SRT timing line")
        start = _parse_timestamp(timing[0])
        end = _parse_timestamp(timing[1])
        if end <= start:
            raise TimelineError("SRT cue end must be greater than start")
        if start < previous_end:
            raise TimelineError("SRT cues must be monotonic and non-overlapping")
        text = " ".join(line.strip() for line in lines[timing_index + 1 :] if line.strip())
        if not text:
            raise TimelineError("SRT cue narration must not be empty")
        cues.append(SrtCue(start=start, end=end, text=text))
        previous_end = end
    if not cues:
        raise TimelineError("SRT contains no usable cues")
    return cues


def parse_srt_file(path: str | Path) -> list[SrtCue]:
    source = Path(path)
    try:
        return parse_srt_text(source.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise TimelineError(f"unable to read timing file {source}: {exc}") from exc


def serialize_srt(cues: Iterable[SrtCue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, 1):
        blocks.append(
            f"{index}\n{_format_timestamp(cue.start)} --> {_format_timestamp(cue.end)}\n{cue.text.strip()}"
        )
    return "\n\n".join(blocks) + "\n"


def _split_clauses(text: str) -> list[str]:
    clauses = [part.strip() for part in _CLAUSE_RE.split(text.strip()) if part.strip()]
    return clauses or [text.strip()]


def _text_weight(text: str) -> int:
    return max(1, len(re.findall(r"\w", text, flags=re.UNICODE)))


def _normalize_tokens(text: str) -> list[str]:
    """Normalize text to lowercase word tokens for alignment matching."""
    return re.findall(r"\w+", text.lower())


def _match_ratio(seq_a: list[str], seq_b: list[str]) -> float:
    """Return SequenceMatcher ratio between two token lists."""
    if not seq_a or not seq_b:
        return 0.0
    return difflib.SequenceMatcher(None, seq_a, seq_b).ratio()


def _canonicalize_narration(cues: list[SrtCue], script: str) -> list[SrtCue]:
    """Align SRT cues to canonical script text using monotonic text-aware matching.

    Design:
    - SRT/speech timing is the timing source-of-truth.
    - The canonical script is used for narration text when alignment is confident.
    - Alignment uses difflib.SequenceMatcher on normalized word tokens — stdlib only.
    - Monotonicity is enforced: script spans only move forward.
    - Low-confidence alignment preserves the original SRT cue text rather than
      arbitrarily assigning an unrelated script clause.
    - When cue count == clause count, direct index mapping is used ONLY when each
      pairwise cue/clause comparison passes the confidence threshold; otherwise
      it falls through to full monotonic alignment.

    For the degenerate case of a single coarse timing cue (no finer SRT boundaries):
    duration-proportion splitting is used as an approximation and documented as such.
    """
    clauses = _split_clauses(script)

    # Exact-count check: direct index mapping may ONLY be used when each
    # corresponding cue/clause pair passes an explicit similarity/confidence check.
    if len(clauses) == len(cues):
        all_confident = True
        for cue, clause in zip(cues, clauses):
            cue_toks = _normalize_tokens(cue.text)
            clause_toks = _normalize_tokens(clause)
            if _match_ratio(cue_toks, clause_toks) < ALIGNMENT_CONFIDENCE_THRESHOLD:
                all_confident = False
                break
        if all_confident:
            return [
                SrtCue(cue.start, cue.end, clauses[index])
                for index, cue in enumerate(cues)
            ]

    # Single coarse cue with multiple script clauses:
    # Text-weight duration splitting is the only option when no finer timing exists.
    # This is an approximation documented explicitly here.
    if len(cues) == 1:
        logger.debug(
            "canonicalize_narration: single coarse cue covering %d script clauses; "
            "using text-weight duration approximation (no finer timing available)",
            len(clauses),
        )
        return _split_long_cue(SrtCue(cues[0].start, cues[0].end, script))

    # General case: monotonic text-aware alignment.
    # For each SRT cue, find the best non-overlapping, monotonic span in the script.
    clause_tokens_list: list[list[str]] = [_normalize_tokens(clause) for clause in clauses]

    result: list[SrtCue] = []
    # script_clause_index: monotonic lower bound — we never go backward
    script_clause_index = 0

    for cue_index, cue in enumerate(cues):
        cue_tokens = _normalize_tokens(cue.text)
        is_last_cue = cue_index == len(cues) - 1

        if is_last_cue:
            # Check remaining clauses for the final cue.
            # Only attach remaining canonical text if it matches final cue sufficiently.
            remaining = clauses[script_clause_index:]
            if remaining:
                remaining_tokens = []
                for cl in remaining:
                    remaining_tokens.extend(_normalize_tokens(cl))
                ratio = _match_ratio(cue_tokens, remaining_tokens)
                if ratio >= ALIGNMENT_CONFIDENCE_THRESHOLD:
                    text = " ".join(remaining).strip()
                else:
                    logger.debug(
                        "canonicalize_narration: low-confidence alignment for final SRT cue %d "
                        "(ratio=%.2f < %.2f); preserving timing-source text %r",
                        cue_index,
                        ratio,
                        ALIGNMENT_CONFIDENCE_THRESHOLD,
                        cue.text[:60],
                    )
                    text = cue.text
            else:
                text = cue.text
            result.append(SrtCue(cue.start, cue.end, text))
            break

        # Search forward from current monotonic position for best-matching clause span
        best_ratio = -1.0
        best_end_index = script_clause_index + 1  # must advance by at least one
        best_span_start = script_clause_index

        # Try single-clause and multi-clause spans from current position forward
        # Limit lookahead to prevent O(n^2) in pathological inputs
        lookahead_limit = min(len(clauses), script_clause_index + 4)
        for span_start in range(script_clause_index, lookahead_limit):
            for span_end in range(
                span_start + 1, min(lookahead_limit + 1, len(clauses) + 1)
            ):
                span_tokens = []
                for ci in range(span_start, span_end):
                    span_tokens.extend(clause_tokens_list[ci])
                ratio = _match_ratio(cue_tokens, span_tokens)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_end_index = span_end
                    best_span_start = span_start

        # Determine confidence and select narration text
        if best_ratio >= ALIGNMENT_CONFIDENCE_THRESHOLD:
            # High-confidence: use canonical script wording for matched span
            actual_start = max(script_clause_index, best_span_start)
            text = " ".join(clauses[actual_start:best_end_index]).strip()
            script_clause_index = best_end_index
        else:
            # Low-confidence: preserve original SRT cue text.
            logger.debug(
                "canonicalize_narration: low-confidence alignment for SRT cue %d "
                "(ratio=%.2f < %.2f); preserving timing-source text %r",
                cue_index,
                best_ratio,
                ALIGNMENT_CONFIDENCE_THRESHOLD,
                cue.text[:60],
            )
            text = cue.text
            # Still advance by one clause to maintain monotonicity
            script_clause_index = min(script_clause_index + 1, len(clauses) - 1)

        result.append(SrtCue(cue.start, cue.end, text))

    return result


def _split_long_cue(cue: SrtCue) -> list[SrtCue]:
    """Split a long cue into visual beats using text-weight duration approximation.

    This function uses text-weight proportional splitting, which is an approximation.
    It is appropriate ONLY when:
    - there is one coarse timing cue
    - finer speech timing is genuinely unavailable
    - the cue needs to be broken into visual beats

    Do NOT use this function to override existing finer SRT boundaries.
    """
    if cue.end - cue.start <= SOFT_MAX_BEAT_SECONDS:
        return [cue]
    clauses = _split_clauses(cue.text)
    if len(clauses) == 1:
        clauses = [part.strip() for part in re.split(r"\s*,\s*", cue.text) if part.strip()]
    if len(clauses) == 1:
        words = cue.text.split()
        chunk_size = max(1, round(len(words) * TARGET_BEAT_SECONDS / (cue.end - cue.start)))
        clauses = [" ".join(words[index : index + chunk_size]) for index in range(0, len(words), chunk_size)]
    total_weight = sum(_text_weight(part) for part in clauses)
    duration = cue.end - cue.start
    result: list[SrtCue] = []
    cursor = cue.start
    for index, part in enumerate(clauses):
        end = cue.end if index == len(clauses) - 1 else cursor + duration * _text_weight(part) / total_weight
        result.append(SrtCue(cursor, end, part))
        cursor = end
    return result


def _merge_short_cues(cues: list[SrtCue]) -> list[SrtCue]:
    merged: list[SrtCue] = []
    for cue in cues:
        if merged and cue.end - merged[-1].start <= SOFT_MAX_BEAT_SECONDS and (
            merged[-1].end - merged[-1].start < MIN_BEAT_SECONDS
            or cue.end - cue.start < MIN_BEAT_SECONDS
        ):
            previous = merged.pop()
            merged.append(SrtCue(previous.start, cue.end, f"{previous.text} {cue.text}".strip()))
        else:
            merged.append(cue)
    if len(merged) > 1 and merged[-1].end - merged[-1].start < MIN_BEAT_SECONDS:
        previous = merged[-2]
        last = merged[-1]
        if last.end - previous.start <= SOFT_MAX_BEAT_SECONDS:
            merged[-2:] = [SrtCue(previous.start, last.end, f"{previous.text} {last.text}".strip())]
    return merged


def _validate_audio_bounds(cues: list[SrtCue], duration: float) -> None:
    """Validate that timeline timing is compatible with the actual audio duration.

    Rules:
    - No cue may begin after the audio duration.
    - The last cue end must not materially exceed audio duration (tolerance applied).
    - A small explicit tolerance covers encoder/SRT rounding (AUDIO_DURATION_TOLERANCE).
    - Gross mismatches (e.g. audio=60s, last cue end=75s) raise TimelineError.
    """
    if not cues or duration <= 0:
        return
    for cue in cues:
        if cue.start > duration + AUDIO_DURATION_TOLERANCE:
            raise TimelineError(
                f"timeline cue starts at {cue.start:.3f}s which exceeds "
                f"audio duration {duration:.3f}s (tolerance {AUDIO_DURATION_TOLERANCE}s)"
            )
    last_end = cues[-1].end
    if last_end > duration + AUDIO_DURATION_TOLERANCE:
        raise TimelineError(
            f"timeline last cue ends at {last_end:.3f}s but audio duration is "
            f"{duration:.3f}s (tolerance {AUDIO_DURATION_TOLERANCE}s) — "
            "check timing_file or audio generation"
        )


def build_timeline_cues(cues: list[SrtCue], script: str) -> list[TimelineCue]:
    canonical = _canonicalize_narration(cues, script)
    fragments = [fragment for cue in canonical for fragment in _split_long_cue(cue)]
    fragments = _merge_short_cues(fragments)
    result = []
    previous_end = 0.0
    for index, cue in enumerate(fragments, 1):
        if cue.start < previous_end or cue.end <= cue.start:
            raise TimelineError("generated timeline is not monotonic")
        result.append(
            TimelineCue(
                id=f"S{index:03d}",
                order=index,
                start=round(cue.start, 3),
                end=round(cue.end, 3),
                narration=cue.text,
            )
        )
        previous_end = cue.end
    return result


def build_timeline_plan(
    project_title: str,
    audio_file: str,
    timing_file: str,
    duration: float,
    cues: list[TimelineCue],
    timing_source: str = "estimated",
) -> TimelinePlan:
    """Build and validate a TimelinePlan.

    Validates audio duration bounds to prevent silently accepting plans where
    timeline extends far past the actual audio duration (e.g., audio=60s, end=75s).
    A small tolerance (AUDIO_DURATION_TOLERANCE) allows for encoder/SRT rounding.
    """
    safe_duration = max(0.0, duration)
    if cues and safe_duration > 0:
        for cue in cues:
            if cue.start > safe_duration + AUDIO_DURATION_TOLERANCE:
                raise TimelineError(
                    f"timeline cue {cue.id!r} starts at {cue.start:.3f}s which exceeds "
                    f"audio duration {safe_duration:.3f}s (tolerance {AUDIO_DURATION_TOLERANCE}s)"
                )
        last_cue = max(cues, key=lambda c: c.order)
        if last_cue.end > safe_duration + AUDIO_DURATION_TOLERANCE:
            raise TimelineError(
                f"timeline last cue {last_cue.id!r} ends at {last_cue.end:.3f}s but "
                f"audio duration is {safe_duration:.3f}s (tolerance {AUDIO_DURATION_TOLERANCE}s) — "
                "check timing_file or audio generation"
            )
    return TimelinePlan(
        schema_version="1.0",
        project_title=project_title,
        audio_file=audio_file,
        timing_file=timing_file,
        duration=safe_duration,
        cues=cues,
        timing_source=timing_source,
    )


def save_timeline_plan(plan: TimelinePlan, destination: str | Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def _write_fallback_srt(path: Path, script: str, duration: float) -> list[SrtCue]:
    """Write a fallback SRT using text-weight duration approximation.

    This is the last-resort timing source when no speech timing is available.
    Text-weight splitting is an approximation; the result is marked as 'estimated'.
    """
    clauses = _split_clauses(script)
    total_weight = sum(_text_weight(clause) for clause in clauses)
    cursor = 0.0
    cues = []
    for index, clause in enumerate(clauses):
        end = duration if index == len(clauses) - 1 else cursor + duration * _text_weight(clause) / total_weight
        cues.append(SrtCue(cursor, end, clause))
        cursor = end
    path.write_text(serialize_srt(cues), encoding="utf-8")
    return cues


def acquire_timing_file(
    *,
    source_timing_file: str | None,
    task_directory: str | Path,
    audio_file: str,
    script: str,
    duration: float,
    sub_maker=None,
    reliable_tts_timing: bool = False,
    whisper_create: Callable[..., object] = subtitle.create,
    subtitle_correct: Callable[..., object] = subtitle.correct,
) -> tuple[str, list[SrtCue], str]:
    """Acquire timing cues from the best available source.

    Returns:
        (timing_file_path, srt_cues, timing_source_label)

    Fallback order:
        1. user-provided timing_file (fails hard on malformed input — no silent fallthrough)
        2. reliable TTS sub_maker timing
        3. Whisper ASR
        4. deterministic text-weight approximation (documented as 'estimated')

    Timing provider failures are logged with exception class and message before
    moving to the next source. KeyboardInterrupt and SystemExit are never swallowed.
    """
    task_directory = Path(task_directory)
    task_directory.mkdir(parents=True, exist_ok=True)
    target = task_directory / "timing.srt"

    # --- Source 1: user-provided timing file ---
    # If supplied but malformed, FAIL clearly. Do not silently fall through to Whisper.
    if source_timing_file:
        try:
            cues = parse_srt_file(source_timing_file)
            target.write_text(serialize_srt(cues), encoding="utf-8")
            return str(target), cues, "user_srt"
        except TimelineError:
            raise

    # --- Source 2: reliable TTS timing ---
    if reliable_tts_timing and sub_maker is not None:
        try:
            voice.create_subtitle(sub_maker=sub_maker, text=script, subtitle_file=str(target))
            cues = parse_srt_file(target)
            return str(target), cues, "tts"
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            logger.warning(
                "TTS timing source failed (%s: %s); falling back to Whisper",
                type(exc).__name__,
                exc,
            )
            target.unlink(missing_ok=True)

    # --- Source 3: Whisper ASR ---
    try:
        whisper_create(audio_file=audio_file, subtitle_file=str(target))
        if target.exists():
            subtitle_correct(subtitle_file=str(target), video_script=script)
            cues = parse_srt_file(target)
            return str(target), cues, "whisper"
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning(
            "Whisper timing source failed (%s: %s); falling back to text-weight estimate",
            type(exc).__name__,
            exc,
        )
        target.unlink(missing_ok=True)

    # --- Source 4: deterministic text-weight approximation ---
    # This is a last-resort approximation. Timing will not reflect actual speech cadence.
    logger.debug(
        "acquire_timing_file: using estimated text-weight fallback for audio_file=%r",
        audio_file,
    )
    cues = _write_fallback_srt(target, script, max(duration, 0.001))
    return str(target), cues, "estimated"


def is_reliable_tts_submaker(sub_maker, voice_name: str) -> bool:
    if sub_maker is None:
        return False
    if getattr(sub_maker, "cues", None):
        return True
    try:
        parsed = voice.parse_voice_name(voice_name)
        return voice.is_azure_v2_voice(parsed) and bool(getattr(sub_maker, "offset", None))
    except Exception:
        return False


def copy_timing_source(source: str, destination: str) -> None:
    shutil.copyfile(source, destination)
