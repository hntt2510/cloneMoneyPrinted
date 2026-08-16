from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AssemblyStatus(str, Enum):
    complete = "complete"
    failed = "failed"


class AssemblyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AudioMixConfig(AssemblyModel):
    narration_volume: float = 1.0
    bgm_file: str | None = None
    bgm_volume: float = 0.2
    ducking_factor: float = 0.5
    fade_in_sec: float = 1.0
    fade_out_sec: float = 1.0


class SubtitleBurnConfig(AssemblyModel):
    enabled: bool = False
    subtitle_file: str | None = None
    font_name: str | None = None
    font_size: int = 36
    font_color: str = "#ffffff"
    stroke_color: str = "#000000"
    stroke_width: int = 2
    bottom_margin: int = 60


class AssemblyScene(AssemblyModel):
    scene_id: str
    order: int
    video_file: str
    sha256: str
    duration_frames: int
    duration_seconds: float
    start_frame: int
    end_frame: int


class AssemblyConfig(AssemblyModel):
    fps: int = 30
    resolution: list[int] = Field(default_factory=lambda: [1920, 1080])
    aspect_ratio: str = "16:9"
    audio_mix: AudioMixConfig = Field(default_factory=AudioMixConfig)
    subtitles: SubtitleBurnConfig = Field(default_factory=SubtitleBurnConfig)
    transition: str = "none"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    preset: str = "medium"
    crf: int = 18


class FinalQCReport(AssemblyModel):
    is_valid: bool
    final_video_file: str
    file_size_bytes: int
    sha256: str
    duration_seconds: float
    fps: float
    resolution: list[int]
    has_video_stream: bool
    has_audio_stream: bool
    video_codec: str | None = None
    audio_codec: str | None = None
    frame_count: int | None = None
    checks_passed: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AssemblyManifest(AssemblyModel):
    schema_version: str = "1.0"
    project_title: str
    project_slug: str
    task_id: str
    source_project_fingerprint: str
    edit_manifest_sha256: str
    assembly_fingerprint: str
    status: AssemblyStatus
    final_video_file: str | None = None
    final_video_sha256: str | None = None
    duration_seconds: float = 0.0
    duration_frames: int = 0
    fps: int = 30
    resolution: list[int] = Field(default_factory=lambda: [1920, 1080])
    scenes: list[AssemblyScene] = Field(default_factory=list)
    audio_mix: AudioMixConfig = Field(default_factory=AudioMixConfig)
    subtitles: SubtitleBurnConfig = Field(default_factory=SubtitleBurnConfig)
    qc_report: FinalQCReport | None = None
    created_at: str
    updated_at: str
    outputs: dict[str, Any] = Field(default_factory=dict)


class AssemblyResult(AssemblyModel):
    status: str
    task_id: str
    final_dir: str
    final_video_file: str | None = None
    assembly_manifest_file: str | None = None
    qc_report_file: str | None = None
    error: str | None = None
