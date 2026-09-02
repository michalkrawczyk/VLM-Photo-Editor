"""Back-compat shim. Use background/providers/ directly for new code."""

from __future__ import annotations

from .providers.base import Candidate
from .providers.replicate import ReplicateProvider


class Generator(ReplicateProvider):
    """Thin shim kept for back-compat. Tests may inject replicate_client here."""

    def __init__(self, replicate_client=None) -> None:
        super().__init__(replicate_client=replicate_client)


__all__ = ["Candidate", "Generator"]
