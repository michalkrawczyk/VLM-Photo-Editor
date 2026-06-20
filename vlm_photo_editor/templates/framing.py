from __future__ import annotations

from vlm_photo_editor.schema.ops import FramingMode

_FOCUS: dict[FramingMode, str] = {
    FramingMode.RULE_OF_THIRDS: "Place subject at a rule-of-thirds intersection; avoid centering.",
    FramingMode.GOLDEN_RATIO: "Align subject to the golden-ratio focal point off-centre.",
    FramingMode.GOLDEN_SPIRAL: "Place subject at the tight curve of the golden spiral.",
    FramingMode.CENTER_SYMMETRY: "Centre subject precisely for formal bilateral symmetry.",
    FramingMode.PORTRAIT_HEADROOM: "Leave breathing room above the head; keep face in upper third; do not clip crown.",
    FramingMode.FACE_ONLY: "Crop tightly around the face; exclude torso; slight chin/forehead margin.",
    FramingMode.NEGATIVE_SPACE: "Push subject to one side; maximise open space on the opposing side.",
    FramingMode.FILL_FRAME: "Fill the frame with subject texture; minimal or no background.",
    FramingMode.LEAD_ROOM: "Subject on trailing edge; open space ahead in direction of gaze or motion.",
    FramingMode.HORIZON_THIRD: "Align horizon to the upper or lower third depending on sky/ground emphasis.",
    FramingMode.CUSTOM: "Apply the user-specified framing — follow the intent description precisely.",
    FramingMode.RECOMMEND_BEST: "",
}

_RATIO: dict[FramingMode, str | None] = {
    FramingMode.RULE_OF_THIRDS: "4:3",
    FramingMode.GOLDEN_RATIO: "1.618:1",
    FramingMode.GOLDEN_SPIRAL: "1.618:1",
    FramingMode.CENTER_SYMMETRY: "1:1",
    FramingMode.PORTRAIT_HEADROOM: "3:4",
    FramingMode.FACE_ONLY: "3:4",
    FramingMode.NEGATIVE_SPACE: "16:9",
    FramingMode.FILL_FRAME: None,
    FramingMode.LEAD_ROOM: "16:9",
    FramingMode.HORIZON_THIRD: "16:9",
    FramingMode.CUSTOM: None,
    FramingMode.RECOMMEND_BEST: None,
}


def focus_instruction(mode: FramingMode) -> str:
    return _FOCUS.get(mode, "")


def frame_ratio_str(mode: FramingMode) -> str | None:
    return _RATIO.get(mode)
