from __future__ import annotations

import json
import re

import structlog

from vlm_photo_editor.models.registry import build_client
from vlm_photo_editor.schema.prefs import EditDelta, LearnedRule

log = structlog.get_logger()

_SYSTEM_PROMPT = """\
You are a photo editing assistant. Analyze these recent editing sessions and find 1-3 recurring \
behavioral patterns worth remembering as preference rules.

Output ONLY valid JSON in this exact format (no other text):
{"rules": [{"description": "concise rule text", "confidence": 0.8}]}

Rules must be concise, actionable, and specific to photo editing style preferences.
If no clear pattern exists, output: {"rules": []}"""


def _build_user_prompt(deltas: list[EditDelta]) -> str:
    lines = ["Recent editing sessions:"]
    for i, d in enumerate(deltas, 1):
        changes = ", ".join(f'"{c}"' for c in d.change_requests) or "none"
        ops = ", ".join(d.accepted_ops) or "none"
        lines.append(f'{i}. intent="{d.intent}" | changes=[{changes}] | ran=[{ops}]')
    return "\n".join(lines)


class Aggregator:
    def aggregate(self, deltas: list[EditDelta]) -> list[LearnedRule]:
        """Summarize edit patterns into candidate preference rules via LLM."""
        if not deltas:
            return []

        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_build_user_prompt(deltas)),
        ]
        try:
            client = build_client("preference_aggregator")
            response = client.invoke(messages)
            text = response.content if hasattr(response, "content") else str(response)
            # Extract JSON object from response (model may add surrounding text)
            match = re.search(r'\{.*"rules".*\}', text, re.DOTALL)
            if not match:
                log.warning("aggregator.no_json_found", response_preview=text[:200])
                return []
            data = json.loads(match.group())
            rules = data.get("rules", [])
            return [
                LearnedRule(
                    description=r["description"],
                    confidence=float(r.get("confidence", 0.5)),
                )
                for r in rules
                if isinstance(r, dict) and r.get("description")
            ]
        except Exception:
            log.warning("aggregator.failed", exc_info=True)
            return []
