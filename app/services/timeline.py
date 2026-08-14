from __future__ import annotations

import re
import shutil
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from app.models.project import TimelineCue, TimelinePlan
from app.services import subtitle, voice

MIN_BEAT_SECONDS = 1.75
TARGET_BEAT_SECONDS = 4.0
SOFT_MAX_BEAT_SECONDS = 6.5
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
        return parse_srt_text(source.read_text(encoding="utf-8"))
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


def _canonicalize_narration(cues: list[SrtCue], script: str) -> list[SrtCue]:
    clauses = _split_clauses(script)
    if len(clauses) == len(cues):
        return [SrtCue(cue.start, cue.end, clauses[index]) for index, cue in enumerate(cues)]

    total_duration = cues[-1].end - cues[0].start
    total_weight = sum(_text_weight(clause) for clause in clauses)
    result: list[SrtCue] = []
    clause_index = 0
    consumed_weight = 0
    for cue_index, cue in enumerate(cues):
        if cue_index == len(cues) - 1:
            end_index = len(clauses)
        else:
            target_weight = total_weight * ((cue.end - cues[0].start) / max(total_duration, 0.001))
            end_index = clause_index
            while end_index < len(clauses) and consumed_weight < target_weight:
                consumed_weight += _text_weight(clauses[end_index])
                end_index += 1
            end_index = max(clause_index + 1, end_index)
        text = " ".join(clauses[clause_index:end_index]).strip()
        if text:
            result.append(SrtCue(cue.start, cue.end, text))
        clause_index = end_index
    if clause_index < len(clauses):
        last = result[-1]
        result[-1] = SrtCue(last.start, last.end, f"{last.text} {' '.join(clauses[clause_index:])}")
    return result


def _split_long_cue(cue: SrtCue) -> list[SrtCue]:
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
) -> TimelinePlan:
    return TimelinePlan(
        schema_version="1.0",
        project_title=project_title,
        audio_file=audio_file,
        timing_file=timing_file,
        duration=max(0.0, duration),
        cues=cues,
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
) -> tuple[str, list[SrtCue]]:
    task_directory = Path(task_directory)
    task_directory.mkdir(parents=True, exist_ok=True)
    target = task_directory / "timing.srt"

    if source_timing_file:
        try:
            cues = parse_srt_file(source_timing_file)
            target.write_text(serialize_srt(cues), encoding="utf-8")
            return str(target), cues
        except TimelineError:
            raise

    if reliable_tts_timing and sub_maker is not None:
        try:
            voice.create_subtitle(sub_maker=sub_maker, text=script, subtitle_file=str(target))
            cues = parse_srt_file(target)
            return str(target), cues
        except Exception:
            target.unlink(missing_ok=True)

    try:
        whisper_create(audio_file=audio_file, subtitle_file=str(target))
        if target.exists():
            subtitle_correct(subtitle_file=str(target), video_script=script)
            cues = parse_srt_file(target)
            return str(target), cues
    except Exception:
        target.unlink(missing_ok=True)

    cues = _write_fallback_srt(target, script, max(duration, 0.001))
    return str(target), cues


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
