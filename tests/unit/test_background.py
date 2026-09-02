from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from vlm_photo_editor.background import run_background_pipeline
from vlm_photo_editor.background.composite import color_match, composite, grain_match
from vlm_photo_editor.background.generator import Candidate, Generator
from vlm_photo_editor.background.providers import (
    GoogleProvider,
    HuggingFaceProvider,
    OpenAIProvider,
    ReplicateProvider,
    get_provider,
    provider_name_for,
)
from vlm_photo_editor.background.quality import GenAISelection, seam_metric, select_best
from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.recipe import GenAIOp

FIXTURES = Path(__file__).parent.parent / "fixtures" / "images"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _container(pixels: np.ndarray | None = None, bit_depth: int = 8) -> ImageContainer:
    if pixels is None:
        pixels = np.random.randint(64, 192, (64, 64, 3), dtype=np.uint8)
    return ImageContainer(
        pixels=pixels,
        bit_depth=bit_depth,
        source_path=Path("fake.jpg"),
    )


def _center_mask(h: int = 64, w: int = 64, margin: int = 16) -> np.ndarray:
    """Bool mask True in the center square."""
    mask = np.zeros((h, w), dtype=bool)
    mask[margin : h - margin, margin : w - margin] = True
    return mask


def _png_bytes(pixels: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(pixels.astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


def _mock_replicate(output_pixels: np.ndarray):
    """Return a fake replicate client that always outputs a fixed image."""
    fake_bytes = _png_bytes(output_pixels)
    output_obj = MagicMock()
    output_obj.read.return_value = fake_bytes

    client = MagicMock()
    client.run.return_value = [output_obj]
    return client


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model,expected_name,expected_type",
    [
        ("black-forest-labs/flux-fill-dev", "replicate", ReplicateProvider),
        ("hf:black-forest-labs/FLUX.1-Fill-dev", "huggingface", HuggingFaceProvider),
        ("openai:gpt-image-1", "openai", OpenAIProvider),
        ("google:imagen-3.0-generate-002", "google", GoogleProvider),
    ],
)
def test_provider_routing(model, expected_name, expected_type):
    assert provider_name_for(model) == expected_name
    assert isinstance(get_provider(model), expected_type)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def test_n_candidates_returned() -> None:
    source = _container()
    mask = _center_mask()
    bg_pixels = np.full((64, 64, 3), 200, dtype=np.uint8)
    gen = Generator(replicate_client=_mock_replicate(bg_pixels))

    candidates = gen.generate(
        source, mask, prompt="blue sky", model="test-model", step_id="s1", n=3
    )

    assert len(candidates) == 3
    assert all(isinstance(c, Candidate) for c in candidates)
    assert all(isinstance(c.genai_op, GenAIOp) for c in candidates)


def test_candidate_seeds_distinct() -> None:
    source = _container()
    mask = _center_mask()
    bg_pixels = np.full((64, 64, 3), 200, dtype=np.uint8)
    gen = Generator(replicate_client=_mock_replicate(bg_pixels))

    candidates = gen.generate(source, mask, prompt="forest", model="test-model", step_id="s1", n=5)

    seeds = [c.genai_op.seed for c in candidates]
    assert len(set(seeds)) == 5, "Expected 5 distinct seeds"


def test_replay_mode_uses_fixed_seed() -> None:
    source = _container()
    mask = _center_mask()
    bg_pixels = np.full((64, 64, 3), 128, dtype=np.uint8)
    gen = Generator(replicate_client=_mock_replicate(bg_pixels))

    candidates = gen.generate(
        source, mask, prompt="sky", model="test-model", step_id="s1", seed=42, n=5
    )

    assert len(candidates) == 1
    assert candidates[0].genai_op.seed == 42


def test_replicate_output_resized_to_source() -> None:
    source = _container(np.random.randint(64, 192, (64, 64, 3), dtype=np.uint8))
    mask = _center_mask()
    bg_pixels = np.full((80, 80, 3), 200, dtype=np.uint8)  # provider snapped to a different size
    gen = Generator(replicate_client=_mock_replicate(bg_pixels))

    candidates = gen.generate(
        source, mask, prompt="blue sky", model="test-model", step_id="s1", n=1
    )

    assert candidates[0].container.pixels.shape[:2] == (64, 64)


def test_kwargs_forwarded_to_replicate() -> None:
    source = _container()
    mask = _center_mask()
    bg_pixels = np.full((64, 64, 3), 100, dtype=np.uint8)
    client = _mock_replicate(bg_pixels)
    gen = Generator(replicate_client=client)

    gen.generate(
        source, mask, prompt="sky", model="test-model", step_id="s1", n=1, guidance_scale=7.5
    )

    call_input = client.run.call_args[1]["input"]
    assert call_input["guidance_scale"] == 7.5


# ---------------------------------------------------------------------------
# BG-P2 — no fabricated seed;  BG-P3 — provider must honour the mask
# ---------------------------------------------------------------------------


def test_genai_op_seed_defaults_to_none() -> None:
    assert GenAIOp(step_id="s1", model="m", prompt="p").seed is None


def test_inject_seeds_skips_steps_without_a_real_seed() -> None:
    """BG-P2: a step whose provider recorded seed=None is regenerated fresh, not
    injected with a meaningless seed."""
    from vlm_photo_editor.recipe.renderer import Renderer
    from vlm_photo_editor.schema.ops import Backend, Op, OpGraph, OpName

    graph = OpGraph(
        ops=[
            Op(
                op_name=OpName.BACKGROUND_REPLACE,
                backend=Backend.GENAI,
                params={"prompt": "sky"},
                step_id="s1",
            )
        ]
    )
    out = Renderer._inject_seeds(graph, [GenAIOp(step_id="s1", model="m", prompt="p", seed=None)])
    assert "seed" not in out.ops[0].params


def test_google_provider_sends_only_masked_crop_and_freezes_subject() -> None:
    """BG-P3: GoogleProvider has no mask API — it must send the model only the masked
    bounding box, leaving subject pixels byte-identical."""
    import sys

    source = _container(np.random.randint(20, 60, (64, 64, 3), dtype=np.uint8))
    mask = _center_mask(margin=16)  # True in [16:48, 16:48] -> 32x32 crop

    captured: dict = {}

    def _fake_edit_image(*, prompt, base_image, number_of_images, **kw):
        captured["size"] = Image.open(io.BytesIO(base_image.image_bytes)).size
        gen = SimpleNamespace(
            image=SimpleNamespace(image_bytes=_png_bytes(np.full((32, 32, 3), 240, dtype=np.uint8)))
        )
        return SimpleNamespace(generated_images=[gen] * number_of_images)

    genai = MagicMock()
    genai.types.Image = lambda image_bytes: SimpleNamespace(image_bytes=image_bytes)
    genai.ImageGenerationModel.return_value.edit_image.side_effect = _fake_edit_image
    google_mod = MagicMock()
    google_mod.generativeai = genai

    with (
        patch.dict(sys.modules, {"google": google_mod, "google.generativeai": genai}),
        patch("vlm_photo_editor.secrets.store.SecretStore.get", return_value="k"),
    ):
        cands = GoogleProvider().generate(
            source, mask, prompt="forest", model="google:imagen-3", step_id="s1", n=1
        )

    assert captured["size"] == (32, 32)  # masked bbox only, not the full 64x64 frame
    out = cands[0].container.pixels
    np.testing.assert_array_equal(out[~mask], source.pixels[~mask])
    assert cands[0].genai_op.seed is None


def test_huggingface_qwen_rejected_before_model_load() -> None:
    """BG-P3 / BG-B7: Qwen cannot inpaint — reject at dispatch, not after a multi-GB load."""
    with pytest.raises(NotImplementedError, match="cannot inpaint"):
        HuggingFaceProvider().generate(
            _container(),
            _center_mask(),
            prompt="x",
            model="hf:Qwen/Qwen2.5-VL-7B-Instruct",
            step_id="s1",
            n=1,
        )


# ---------------------------------------------------------------------------
# Composite — subject pixel freeze
# ---------------------------------------------------------------------------


def test_subject_pixels_unchanged_after_color_match() -> None:
    source = _container(np.random.randint(50, 150, (64, 64, 3), dtype=np.uint8))
    generated = _container(np.random.randint(150, 250, (64, 64, 3), dtype=np.uint8))
    mask = _center_mask()

    result = color_match(source, generated, mask)

    assert np.all(result.pixels[~mask] == generated.pixels[~mask])


def test_subject_pixels_unchanged_after_grain_match() -> None:
    source = _container(np.random.randint(50, 150, (64, 64, 3), dtype=np.uint8))
    generated = _container(np.random.randint(150, 250, (64, 64, 3), dtype=np.uint8))
    mask = _center_mask()

    result = grain_match(source, generated, mask)

    assert np.all(result.pixels[~mask] == generated.pixels[~mask])


def test_subject_pixels_unchanged_after_composite() -> None:
    """Hard DoD invariant: subject pixels are byte-identical after full composite.

    Uses a 200×200 image so pixels well outside the feather zone exist.
    """
    rng = np.random.default_rng(0)
    src_pixels = rng.integers(50, 150, (200, 200, 3), dtype=np.uint8)
    gen_pixels = rng.integers(150, 250, (200, 200, 3), dtype=np.uint8)
    source = _container(src_pixels)
    generated = _container(gen_pixels)
    mask = _center_mask(200, 200, margin=50)

    result = composite(source, generated, mask, feather_px=10)

    # Pixels outside 3*feather_px from the mask boundary must equal source exactly.
    from scipy.ndimage import binary_dilation

    safe_outside = ~binary_dilation(mask, iterations=30)
    assert safe_outside.any(), "Test setup error: no safe pixels outside feather zone"
    assert np.all(result.pixels[safe_outside] == source.pixels[safe_outside])


def test_composite_modifies_masked_region() -> None:
    # Use random pixels so color_match computes non-degenerate std and preserves
    # the difference between source and generated regions.
    rng = np.random.default_rng(1)
    src_pixels = rng.integers(40, 80, (64, 64, 3), dtype=np.uint8)
    gen_pixels = rng.integers(160, 200, (64, 64, 3), dtype=np.uint8)
    source = _container(src_pixels)
    generated = _container(gen_pixels)
    mask = _center_mask()

    result = composite(source, generated, mask, feather_px=5)

    # Interior was composited from the generated background — not byte-identical to source
    interior = np.zeros_like(mask)
    interior[24:40, 24:40] = True
    assert not np.array_equal(result.pixels[interior], src_pixels[interior])


# ---------------------------------------------------------------------------
# Color match — LAB stats transfer
# ---------------------------------------------------------------------------


def test_color_match_lab_stats() -> None:
    """Generated region LAB mean should move toward source border ring stats."""
    src_pixels = np.full((64, 64, 3), 80, dtype=np.uint8)
    gen_pixels = np.full((64, 64, 3), 200, dtype=np.uint8)
    source = _container(src_pixels)
    generated = _container(gen_pixels)
    mask = _center_mask()

    result = color_match(source, generated, mask)

    from skimage.color import rgb2lab

    result_f = result.pixels.astype(np.float64) / 255.0
    result_lab = rgb2lab(result_f)
    src_f = src_pixels.astype(np.float64) / 255.0
    src_lab = rgb2lab(src_f)

    result_mean_L = result_lab[mask, 0].mean()
    src_mean_L = src_lab[~mask, 0].mean()
    gen_mean_L = rgb2lab(gen_pixels.astype(np.float64) / 255.0)[mask, 0].mean()

    # After transfer, result should be closer to source lightness than original generated
    assert abs(result_mean_L - src_mean_L) < abs(gen_mean_L - src_mean_L)


# ---------------------------------------------------------------------------
# Seam metric and quality gate
# ---------------------------------------------------------------------------


def test_seam_metric_low_for_smooth_composite() -> None:
    """A perfectly uniform image should have near-zero seam metric."""
    container = _container(np.full((64, 64, 3), 128, dtype=np.uint8))
    mask = _center_mask()
    metric = seam_metric(container, mask)
    assert metric < 1.0


def test_seam_gate_pass() -> None:
    """select_best returns needs_manual=False when best candidate meets threshold."""
    source = _container(np.full((64, 64, 3), 100, dtype=np.uint8))
    # Generated close to source → smooth seam after composite
    generated = _container(np.full((64, 64, 3), 110, dtype=np.uint8))
    mask = _center_mask()
    cand = Candidate(
        container=generated, genai_op=GenAIOp(step_id="s1", model="m", prompt="p", seed=1)
    )

    selection = select_best(source, [cand], mask, threshold=100.0)

    assert selection.needs_manual is False


def test_seam_gate_picks_best_candidate() -> None:
    """select_best picks the candidate with the lowest seam metric."""
    source = _container(np.full((64, 64, 3), 100, dtype=np.uint8))
    good = _container(np.full((64, 64, 3), 105, dtype=np.uint8))
    bad = _container(np.full((64, 64, 3), 220, dtype=np.uint8))
    mask = _center_mask()
    cands = [
        Candidate(container=bad, genai_op=GenAIOp(step_id="s1", model="m", prompt="p", seed=1)),
        Candidate(container=good, genai_op=GenAIOp(step_id="s1", model="m", prompt="p", seed=2)),
    ]

    selection = select_best(source, cands, mask, threshold=100.0)

    assert selection.best_candidate.genai_op.seed == 2
    # Every candidate is scored and returned, best first (BG-U2).
    assert [s.candidate.genai_op.seed for s in selection.scored] == [2, 1]


def test_seam_gate_reroll() -> None:
    """select_best calls generator for extra seeds when first batch fails."""
    source = _container(np.full((64, 64, 3), 100, dtype=np.uint8))
    bad_gen = _container(np.full((64, 64, 3), 220, dtype=np.uint8))
    mask = _center_mask()
    bad_cand = Candidate(
        container=bad_gen, genai_op=GenAIOp(step_id="s1", model="m", prompt="p", seed=1)
    )

    # Mock generator that returns a good candidate on re-roll
    good_gen_pixels = np.full((64, 64, 3), 105, dtype=np.uint8)
    mock_client = _mock_replicate(good_gen_pixels)
    generator = Generator(replicate_client=mock_client)

    # threshold=0.0 forces the first candidate to fail so extra seeds are requested.
    select_best(source, [bad_cand], mask, threshold=0.0, extra_seeds=1, provider=generator)

    assert mock_client.run.called


def test_seam_gate_flag_for_manual() -> None:
    """select_best returns needs_manual=True when all seeds fail and no generator."""
    source = _container(np.full((64, 64, 3), 100, dtype=np.uint8))
    bad_gen = _container(np.full((64, 64, 3), 220, dtype=np.uint8))
    mask = _center_mask()
    cands = [
        Candidate(container=bad_gen, genai_op=GenAIOp(step_id="s1", model="m", prompt="p", seed=i))
        for i in range(3)
    ]

    selection = select_best(source, cands, mask, threshold=0.0, extra_seeds=0, provider=None)

    assert selection.needs_manual is True


class _StubProvider:
    """Returns fixed candidates and counts generate() calls."""

    def __init__(self, pixels: list[np.ndarray], step_id: str = "s1") -> None:
        self._pixels = pixels
        self._step_id = step_id
        self.calls = 0

    def generate(self, container, mask, prompt, model, step_id, n=3, seed=None, **kwargs):
        self.calls += 1
        return [
            Candidate(
                container=_container(px),
                genai_op=GenAIOp(step_id=self._step_id, model=model, prompt=prompt, seed=i),
            )
            for i, px in enumerate(self._pixels)
        ]


def test_select_best_rejects_empty_candidate_list() -> None:
    """BG-B9: an empty candidate list fails loudly instead of IndexError."""
    source = _container(np.full((64, 64, 3), 100, dtype=np.uint8))
    with pytest.raises(ValueError, match="at least one candidate"):
        select_best(source, [], _center_mask())


def test_select_best_survives_empty_reroll() -> None:
    """BG-B9: a provider returning [] on re-roll flags for manual review, not IndexError."""
    source = _container(np.full((64, 64, 3), 100, dtype=np.uint8))
    bad = _container(np.full((64, 64, 3), 220, dtype=np.uint8))
    cand = Candidate(container=bad, genai_op=GenAIOp(step_id="s1", model="m", prompt="p", seed=1))
    empty_provider = _StubProvider([])

    selection = select_best(
        source,
        [cand],
        _center_mask(),
        threshold=0.0,
        extra_seeds=2,
        provider=empty_provider,
    )

    assert empty_provider.calls == 1
    assert selection.needs_manual is True
    assert len(selection.scored) == 1


def test_select_best_override_index_wins() -> None:
    """BG-U2: an explicit override takes that candidate regardless of its metric."""
    source = _container(np.full((64, 64, 3), 100, dtype=np.uint8))
    good = _container(np.full((64, 64, 3), 105, dtype=np.uint8))
    bad = _container(np.full((64, 64, 3), 220, dtype=np.uint8))
    cands = [
        Candidate(container=bad, genai_op=GenAIOp(step_id="s1", model="m", prompt="p", seed=1)),
        Candidate(container=good, genai_op=GenAIOp(step_id="s1", model="m", prompt="p", seed=2)),
    ]

    selection = select_best(source, cands, _center_mask(), threshold=100.0, override_index=1)

    assert selection.best_candidate.genai_op.seed == 1  # the worse-scoring one, as asked
    assert selection.needs_manual is False


def test_pipeline_defaults_read_settings(monkeypatch) -> None:
    """BG-C3: threshold and feather_px default to AppSettings, not hardcoded literals."""
    from vlm_photo_editor.config.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "seam_threshold", 0.0)  # unreachable → always flags
    source = _container(np.full((64, 64, 3), 100, dtype=np.uint8))

    _, _, needs_manual, _ = run_background_pipeline(
        source,
        _center_mask(),
        prompt="sky",
        model="test-model",
        step_id="s1",
        n_candidates=1,
        provider=_StubProvider([np.full((64, 64, 3), 220, dtype=np.uint8)]),
    )

    assert needs_manual is True


def test_executor_exposes_candidates_and_replays_override(monkeypatch) -> None:
    """BG-U2: candidates reach ExecutionResult; an override replays them without
    a second provider call."""
    import vlm_photo_editor.background as background
    from vlm_photo_editor.ops.executor import Executor
    from vlm_photo_editor.schema.ops import Backend, BoundingBox, Op, OpGraph, OpName

    provider = _StubProvider(
        [
            np.full((64, 64, 3), 105, dtype=np.uint8),
            np.full((64, 64, 3), 220, dtype=np.uint8),
        ]
    )
    monkeypatch.setattr(background, "get_provider", lambda model: provider)

    container = _container(np.full((64, 64, 3), 100, dtype=np.uint8))
    op = Op(
        op_name=OpName.BACKGROUND_REPLACE,
        params={"prompt": "sky", "model": "test-model", "n": 2},
        backend=Backend.GENAI,
        step_id="s1",
        bbox=BoundingBox(x=16, y=16, width=32, height=32),
    )
    graph = OpGraph(ops=[op])

    result = Executor().apply(container, graph)
    scored = result.genai_candidates["s1"]

    assert provider.calls == 1
    assert len(scored) == 2
    assert [s.metric for s in scored] == sorted(s.metric for s in scored)

    replayed = Executor().apply(
        container,
        graph,
        {"s1": GenAISelection(candidates=[s.candidate for s in scored], override_index=1)},
    )

    assert provider.calls == 1  # no second generation
    np.testing.assert_array_equal(replayed.container.pixels, scored[1].composite.pixels)


# ---------------------------------------------------------------------------
# Replay determinism
# ---------------------------------------------------------------------------


def test_replay_deterministic() -> None:
    """Same seed → byte-identical output from mock generator."""
    source = _container(np.random.randint(50, 150, (64, 64, 3), dtype=np.uint8))
    mask = _center_mask()
    fixed_pixels = np.random.randint(150, 250, (64, 64, 3), dtype=np.uint8)
    model = "test-model"

    gen = Generator(replicate_client=_mock_replicate(fixed_pixels))

    result1, op1, _, _ = run_background_pipeline(
        source,
        mask,
        prompt="sky",
        model=model,
        step_id="s1",
        n_candidates=1,
        seed=77,
        provider=gen,
    )
    result2, op2, _, _ = run_background_pipeline(
        source,
        mask,
        prompt="sky",
        model=model,
        step_id="s1",
        n_candidates=1,
        seed=77,
        provider=gen,
    )

    assert op1.seed == op2.seed == 77
    np.testing.assert_array_equal(result1.pixels, result2.pixels)


# ---------------------------------------------------------------------------
# Integration with real fixture image
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_pipeline_with_fixture_image() -> None:
    src = FIXTURES / "sample.jpg"
    if not src.exists():
        pytest.skip("fixture image not available")

    from vlm_photo_editor.imageio.loaders import load

    container = load(src)
    h, w = container.height, container.width
    mask = np.zeros((h, w), dtype=bool)
    mask[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4] = True

    fixed_pixels = np.random.randint(100, 200, (h, w, 3), dtype=np.uint8)
    gen = Generator(replicate_client=_mock_replicate(fixed_pixels))

    result, genai_op, needs_manual, _ = run_background_pipeline(
        container,
        mask,
        prompt="blue sky",
        model="test-model",
        step_id="s1",
        n_candidates=2,
        provider=gen,
    )

    assert result.pixels.shape == container.pixels.shape
    assert isinstance(genai_op, GenAIOp)
    assert genai_op.seed is not None
