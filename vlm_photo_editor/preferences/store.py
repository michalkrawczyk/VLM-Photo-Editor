from __future__ import annotations

import json
import uuid
from pathlib import Path

from vlm_photo_editor.schema.prefs import (
    EditDelta,
    ExplicitRule,
    LearnedRule,
    Preferences,
)

_DEFAULT_PREFS_PATH = Path.home() / ".vlm_photo_editor" / "preferences.json"
_DEFAULT_DELTA_PATH = Path.home() / ".vlm_photo_editor" / "deltas.jsonl"

AGGREGATE_AFTER = 5


class PreferenceStore:
    def __init__(self, path: Path = _DEFAULT_PREFS_PATH) -> None:
        self._path = path

    def load(self) -> Preferences:
        if not self._path.exists():
            return Preferences()
        return Preferences.model_validate_json(self._path.read_text())

    def save(self, prefs: Preferences) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(prefs.model_dump_json(indent=2))

    def add_explicit(self, description: str) -> ExplicitRule:
        prefs = self.load()
        rule = ExplicitRule(description=description)
        prefs.explicit.append(rule)
        prefs.version = str(uuid.uuid4())
        self.save(prefs)
        return rule

    def remove_explicit(self, rule_id: str) -> None:
        prefs = self.load()
        prefs.explicit = [r for r in prefs.explicit if r.rule_id != rule_id]
        prefs.version = str(uuid.uuid4())
        self.save(prefs)

    def toggle_rule(self, rule_id: str) -> None:
        prefs = self.load()
        for rule in prefs.explicit:
            if rule.rule_id == rule_id:
                rule.active = not rule.active
                prefs.version = str(uuid.uuid4())
                self.save(prefs)
                return
        for rule in prefs.learned:
            if rule.rule_id == rule_id:
                rule.active = not rule.active
                prefs.version = str(uuid.uuid4())
                self.save(prefs)
                return

    def add_learned(self, candidates: list[LearnedRule]) -> None:
        prefs = self.load()
        existing_ids = {r.rule_id for r in prefs.learned}
        for candidate in candidates:
            if candidate.rule_id not in existing_ids:
                prefs.learned.append(candidate)
        prefs.version = str(uuid.uuid4())
        self.save(prefs)

    def approve_learned(self, rule_id: str) -> None:
        prefs = self.load()
        for rule in prefs.learned:
            if rule.rule_id == rule_id:
                rule.approved = True
                rule.active = True
                prefs.version = str(uuid.uuid4())
                self.save(prefs)
                return


class DeltaStore:
    def __init__(self, path: Path = _DEFAULT_DELTA_PATH) -> None:
        self._path = path

    def append(self, delta: EditDelta) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a") as f:
            f.write(delta.model_dump_json() + "\n")

    def list(self) -> list[EditDelta]:
        if not self._path.exists():
            return []
        deltas: list[EditDelta] = []
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if line:
                deltas.append(EditDelta.model_validate(json.loads(line)))
        return deltas

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()
