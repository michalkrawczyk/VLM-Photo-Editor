"""Fixtures for live-browser e2e tests: real Streamlit server, real Anthropic API,
real MediaPipe detection. See agent_notes/commands.md for how to run these.

All fixtures here are session-scoped where possible to avoid repeated ~10s server
startup / model download cost across the handful of e2e tests.
"""

from __future__ import annotations

import importlib.util
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "samples"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODELS_DIR = Path(__file__).resolve().parent / "models"
YOLO_ONNX_DEFAULT_PATH = REPO_ROOT / "infer_models" / "yolo" / "yolo26s.onnx"

MEDIAPIPE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/object_detector/"
    "efficientdet_lite0/int8/1/efficientdet_lite0.tflite"
)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    """Dump screenshot + DOM + server log on failure — the app swallows errors into a
    UI banner, so without this a failed run leaves nothing to diagnose from."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", item.name)
    page = item.funcargs.get("page")
    if page is not None:
        try:
            page.screenshot(path=str(ARTIFACTS_DIR / f"{stem}_FAIL.png"), full_page=True)
        except Exception:
            pass
        try:
            (ARTIFACTS_DIR / f"{stem}_FAIL.html").write_text(page.content(), encoding="utf-8")
        except Exception:
            pass

    log_path = ARTIFACTS_DIR / "streamlit_server.log"
    if log_path.exists():
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
        (ARTIFACTS_DIR / f"{stem}_FAIL.serverlog.txt").write_text("\n".join(tail), encoding="utf-8")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("localhost", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def sample_image_jpg() -> Path:
    return SAMPLES_DIR / "Gemini_Generated_Image_wqnetmwqnetmwqne.jpg"


@pytest.fixture(scope="session")
def sample_image_png() -> Path:
    return SAMPLES_DIR / "Gemini_Generated_Image_wqnetmwqnetmwqne.png"


@pytest.fixture(scope="session")
def screenshot_dir() -> Path:
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    return ARTIFACTS_DIR


@pytest.fixture(scope="session")
def mediapipe_model_path() -> Path:
    override = os.environ.get("E2E_MEDIAPIPE_MODEL_PATH")
    if override:
        path = Path(override)
        if not path.is_file():
            pytest.fail(f"E2E_MEDIAPIPE_MODEL_PATH={override!r} does not point to a file")
        return path

    MODELS_DIR.mkdir(exist_ok=True)
    dest = MODELS_DIR / "efficientdet_lite0.tflite"
    if not dest.exists():
        try:
            urllib.request.urlretrieve(MEDIAPIPE_MODEL_URL, dest)
        except Exception as exc:
            pytest.fail(
                f"Failed to download MediaPipe object-detector model from "
                f"{MEDIAPIPE_MODEL_URL}: {exc}. Set E2E_MEDIAPIPE_MODEL_PATH to a "
                f"local .tflite file to bypass the download."
            )
    return dest


_MEDIAPIPE_PROBE = """
import numpy as np, mediapipe as mp
opts = mp.tasks.vision.ObjectDetectorOptions(
    base_options=mp.tasks.BaseOptions(model_asset_path={path!r}), max_results=1
)
det = mp.tasks.vision.ObjectDetector.create_from_options(opts)
det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((64, 64, 3), dtype=np.uint8)))
"""


@pytest.fixture(scope="session")
def mediapipe_usable(mediapipe_model_path: Path) -> bool:
    """Whether mediapipe detection actually runs here, probed out-of-process.

    Its TFLite binary is compiled with AVX and aborts the whole process
    (SIGILL) on a CPU without it — inside a VM that hides AVX, selecting
    Character Focus 'mediapipe' takes the Streamlit server down with it, so
    tests must check before driving that path, not after.
    """
    probe = subprocess.run(
        [sys.executable, "-c", _MEDIAPIPE_PROBE.format(path=str(mediapipe_model_path))],
        capture_output=True,
        timeout=120,
    )
    return probe.returncode == 0


@pytest.fixture(scope="session")
def yolo_onnx_model_path() -> Path | None:
    """Local YOLO detection ``.onnx`` for the ``yolo_onnx`` Character Focus backend.

    No download (Ultralytics AGPL, no hosted asset): ``E2E_YOLO_ONNX_MODEL_PATH``
    if set, else the gitignored local ``infer_models/yolo/yolo26s.onnx`` (also the
    app's bundled default), else ``None`` — the ``yolo_onnx`` e2e case then skips.
    """
    override = os.environ.get("E2E_YOLO_ONNX_MODEL_PATH")
    if override:
        path = Path(override)
        if not path.is_file():
            pytest.fail(f"E2E_YOLO_ONNX_MODEL_PATH={override!r} does not point to a file")
        return path
    return YOLO_ONNX_DEFAULT_PATH if YOLO_ONNX_DEFAULT_PATH.is_file() else None


@pytest.fixture(scope="session")
def yolo_onnx_usable(yolo_onnx_model_path: Path | None) -> bool:
    """Whether the ``yolo_onnx`` backend can actually load the configured model here.

    onnxruntime's CPU EP raises an ordinary exception on a missing/incompatible
    file — no AVX-SIGILL trap like mediapipe's TFLite binary — so an in-process
    probe is enough.
    """
    if yolo_onnx_model_path is None or importlib.util.find_spec("onnxruntime") is None:
        return False
    # yolo_onnx now also needs a sibling classes.txt naming a human/person class,
    # or ready_backends() drops it and the picker never lists it.
    try:
        from vlm_photo_editor.detection._common import has_human_label, load_class_labels

        if not has_human_label(load_class_labels(yolo_onnx_model_path)):
            return False
    except ValueError:
        return False
    try:
        import onnxruntime as ort

        ort.InferenceSession(str(yolo_onnx_model_path), providers=["CPUExecutionProvider"])
    except Exception:
        return False
    return True


@pytest.fixture(scope="session")
def streamlit_server(mediapipe_model_path: Path) -> Iterator[str]:
    port = _free_port()
    env = os.environ.copy()
    env["MEDIAPIPE_MODEL_PATH"] = str(mediapipe_model_path)
    _yolo_path = os.environ.get("E2E_YOLO_ONNX_MODEL_PATH") or (
        str(YOLO_ONNX_DEFAULT_PATH) if YOLO_ONNX_DEFAULT_PATH.is_file() else None
    )
    if _yolo_path:
        env["YOLO_ONNX_MODEL_PATH"] = _yolo_path

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    log_path = ARTIFACTS_DIR / "streamlit_server.log"
    log_file = open(log_path, "w", encoding="utf-8")

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(REPO_ROOT / "vlm_photo_editor" / "app" / "main.py"),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    base_url = f"http://localhost:{port}"
    deadline = time.monotonic() + 60
    healthy = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log_file.close()
            pytest.fail(f"Streamlit server exited early (code {proc.returncode}); see {log_path}")
        try:
            with urllib.request.urlopen(f"{base_url}/_stcore/health", timeout=2) as resp:
                if resp.status == 200:
                    healthy = True
                    break
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(0.5)

    if not healthy:
        proc.terminate()
        log_file.close()
        pytest.fail(f"Streamlit server did not become healthy within 60s; see {log_path}")

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    log_file.close()
