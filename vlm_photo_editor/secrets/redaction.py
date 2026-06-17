from __future__ import annotations

import logging
import re

_KEY_PATTERN = re.compile(r"(?:sk-|r8_)[A-Za-z0-9]{20,}")


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _KEY_PATTERN.sub("[REDACTED]", str(record.msg))
        record.args = ()
        return True


def install_redaction_filter() -> None:
    logging.getLogger().addFilter(RedactionFilter())
