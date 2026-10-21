from __future__ import annotations

import logging
import re

_KEY_PATTERN = re.compile(r"(?:sk-ant-|sk-|r8_)[A-Za-z0-9\-]{20,}")
_INSTALLED_MARK = "_vlm_redaction_installed"


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            formatted = record.getMessage()
        except TypeError:
            formatted = str(record.msg)
        record.msg = _scrub(formatted)
        record.args = ()
        return True


def _scrub(value):
    """Redact key-shaped substrings in a str, recursing into dict/list/tuple."""
    if isinstance(value, str):
        return _KEY_PATTERN.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if type(value) in (list, tuple):
        return type(value)(_scrub(v) for v in value)
    return value


def redaction_processor(logger, method_name, event_dict):
    """structlog processor: scrub every string in the event before it is rendered."""
    return _scrub(event_dict)


def install_redaction_filter() -> None:
    """Scrub key-shaped strings from every stdlib and structlog record. Idempotent.

    SR-P1: a `logging.Filter` on the root *logger* only sees records logged through the
    root itself, and structlog never consults stdlib filters. So the stdlib side wraps the
    record factory (covers every logger and handler, including ones created later) and the
    structlog side inserts a processor just ahead of the renderer.
    """
    import structlog

    current = logging.getLogRecordFactory()
    if not getattr(current, _INSTALLED_MARK, False):
        scrub = RedactionFilter()

        def factory(*args, **kwargs):
            record = current(*args, **kwargs)
            scrub.filter(record)
            return record

        setattr(factory, _INSTALLED_MARK, True)
        logging.setLogRecordFactory(factory)

    processors = list(structlog.get_config()["processors"])
    if redaction_processor not in processors:
        processors.insert(max(len(processors) - 1, 0), redaction_processor)
        structlog.configure(processors=processors)
