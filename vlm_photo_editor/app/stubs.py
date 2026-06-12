"""Mock data for P0.5 UI shell. Replaced by real backend wiring in P7."""
from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName, RiskTier
from vlm_photo_editor.schema.plan import HumanPlan, HumanStep
from vlm_photo_editor.schema.prefs import ExplicitRule, LearnedRule, Preferences

MOCK_PLAN = HumanPlan(
    plan_id="mock-plan-001",
    steps=[
        HumanStep(
            step_id="step-001",
            index=1,
            title="Replace background",
            why="Current background is distracting",
            op_names=["background_replace"],
        ),
        HumanStep(
            step_id="step-002",
            index=2,
            title="Adjust exposure",
            why="Subject is slightly underexposed",
            op_names=["exposure"],
        ),
        HumanStep(
            step_id="step-003",
            index=3,
            title="Apply portrait framing",
            why="Better composition with rule of thirds",
            op_names=["crop"],
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
]

PROVIDERS = ["anthropic", "openai", "replicate"]
