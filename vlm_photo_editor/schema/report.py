from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CastLabel = Literal["warm", "cool", "neutral"]


class ExifSummary(BaseModel):
    """Whitelisted capture metadata; GPS, serials and owner fields are never kept."""

    iso: int | None = None
    exposure_time_s: float | None = None
    f_number: float | None = None
    focal_length_mm: float | None = None
    wb_mode: Literal["auto", "manual"] | None = None
    exposure_bias_ev: float | None = None


class ImageReport(BaseModel):
    """Deterministic measurements of one image, handed to the planner as ground truth.

    Computed locally by ``analysis.compute_report`` (no VLM, no network). Luma and the
    ``clipped_*`` / ``saturation_mean`` / ``channel_means`` fields are display-referred
    (computed on gamma-encoded values scaled to 0-1); ``cast_*`` and
    ``suggested_wb_temperature`` use linear light, matching what ``white_balance`` does.
    """

    width: int
    height: int

    luma_mean: float = Field(description="Mean Rec.709 luma, 0-1.")
    luma_p1: float
    luma_p5: float
    luma_p50: float
    luma_p95: float
    luma_p99: float
    clipped_shadow_pct: float = Field(description="% of pixels with every channel <= 2/255.")
    clipped_highlight_pct: float = Field(description="% of pixels with any channel >= 253/255.")

    channel_means: tuple[float, float, float] = Field(description="Mean R, G, B, 0-1.")
    cast_rb_ratio: float = Field(description="Linear-light mean R / mean B (gray-world).")
    cast_label: CastLabel
    suggested_wb_temperature: float = Field(
        description="white_balance.temperature (Lightroom convention) that equalises mean R and "
        "B under a gray-world assumption; unreliable for scenes dominated by one colour."
    )
    saturation_mean: float = Field(description="Mean HSV saturation, 0-1.")

    sharpness: float = Field(
        description="Laplacian variance of 0-255 luma on a <=1024 px long-edge copy."
    )
    noise_sigma: float = Field(description="Immerkaer noise sigma, 0-255 luma, native-res crop.")

    tilt_deg: float | None = Field(
        default=None,
        description="Visual counter-clockwise tilt of near-horizontal/vertical structure, "
        "degrees. Rotate by -tilt_deg to level. None when no usable lines were found.",
    )
    tilt_confidence: float | None = Field(
        default=None, description="0-1 agreement/coverage of the tilt estimate; None with tilt."
    )

    exif: ExifSummary = Field(default_factory=ExifSummary)


class StepCheck(BaseModel):
    """One deterministic before/after check of an edit (Critic stage 1).

    Derived from what an op *should* do (exposure +EV => median luma up), measured on the
    ``ImageReport`` of the original and of the result. ``step_id`` links back to the plan.
    """

    step_id: str | None = None
    op_name: str
    metric: str = Field(description="ImageReport field the check reads.")
    expected: Literal["increase", "decrease", "not_increase"]
    before: float
    after: float
    ok: bool

    def describe(self) -> str:
        verb = {"increase": "rise", "decrease": "fall", "not_increase": "not rise"}[self.expected]
        verdict = "ok" if self.ok else "FAILED"
        return (
            f"{self.op_name}: {self.metric} should {verb}; measured "
            f"{self.before:.3g} -> {self.after:.3g} ({verdict})"
        )
