"""Mock data for P0.5 UI shell. Replaced by real backend wiring in P7."""

from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName, RiskTier
from vlm_photo_editor.schema.plan import HumanPlan, HumanStep
from vlm_photo_editor.schema.prefs import ExplicitRule, LearnedRule, Preferences

MOCK_PLAN = HumanPlan(
    plan_id="mock-plan-001",
    steps=[
        HumanStep(
            index=1,
            title="Replace background",
            why="Current background is distracting",
            op_names=["background_replace"],
            op_params=[{}],
        ),
        HumanStep(
            index=2,
            title="Adjust exposure",
            why="Subject is slightly underexposed",
            op_names=["exposure"],
            op_params=[{}],
        ),
        HumanStep(
            index=3,
            title="Apply portrait framing",
            why="Better composition with rule of thirds",
            op_names=["crop"],
            op_params=[{}],
        ),
    ],
    mode="full",
)

MOCK_OPGRAPH = OpGraph(
    ops=[
        Op(
            op_name=OpName.BACKGROUND_REPLACE,
            backend=Backend.GENAI,
            params={"prompt": "blurred bokeh outdoor scene"},
            risk_tier=RiskTier.HIGH,
            step_id="step-001",
        ),
        Op(
            op_name=OpName.EXPOSURE,
            backend=Backend.PIL,
            params={"ev": 0.3},
            risk_tier=RiskTier.LOW,
            step_id="step-002",
        ),
        Op(
            op_name=OpName.CROP,
            backend=Backend.PIL,
            params={"left": 50, "top": 0, "right": 950, "bottom": 800},
            risk_tier=RiskTier.LOW,
            step_id="step-003",
        ),
    ]
)

MOCK_PREFS = Preferences(
    explicit=[
        ExplicitRule(rule_id="er-001", description="Prefer warm color tones"),
        ExplicitRule(rule_id="er-002", description="Keep portrait headroom >= 10%"),
    ],
    learned=[
        LearnedRule(
            rule_id="lr-001",
            description="User frequently increases exposure by +0.3 EV",
            confidence=0.85,
            approved=True,
            active=True,
        ),
    ],
)

MODEL_ROLES = ["planner", "critic", "preference_aggregator"]

AVAILABLE_MODELS = [
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-8",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "LiquidAI/LFM2.5-1.2B-Instruct",
]

PROVIDERS = ["anthropic", "openai", "replicate"]

LOCAL_MODEL_IDS: frozenset[str] = frozenset(
    {
        "LiquidAI/LFM2.5-1.2B-Instruct",
        "LiquidAI/LFM2.5-VL-1.6B",
    }
)

_MODEL_ID_TO_PROVIDER: dict[str, str] = {
    "claude-sonnet-4-6": "anthropic",
    "claude-haiku-4-5-20251001": "anthropic",
    "claude-opus-4-8": "anthropic",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "gpt-4.1-mini": "openai",
    "LiquidAI/LFM2.5-1.2B-Instruct": "local",
}


def provider_for_model(model_id: str) -> str:
    """Return provider string for a model_id in AVAILABLE_MODELS. Defaults to 'anthropic'."""
    return _MODEL_ID_TO_PROVIDER.get(model_id, "anthropic")
