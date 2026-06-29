"""PII detection and redaction using Microsoft Presidio.

Presidio uses a spaCy NER model (en_core_web_lg) to detect named entities
that overlap with PII recognisers (EMAIL_ADDRESS, PHONE_NUMBER,
CREDIT_CARD, PERSON, LOCATION, etc.).

Lazy initialisation: the spaCy model loads on first call, not at import
time, so the startup cost is paid once and only when a query arrives.

All external failures degrade gracefully: if Presidio is unavailable the
original text is returned unchanged and a warning is logged. PII redaction
must never crash the service.

Why call this before any LLM call AND before writing to state:
- LangSmith captures inputs by default. Writing the redacted text to state
  before returning from the node ensures the trace sees scrubbed text, not
  the raw PII. Redaction that only happens before the model call but after
  state assignment leaks PII into traces.
"""

import logging

logger = logging.getLogger(__name__)

# Lazy-loaded Presidio engines — heavy: spaCy model load takes ~2s on first call
_analyzer = None
_anonymizer = None


def _get_engines():
    global _analyzer, _anonymizer
    if _analyzer is not None:
        return _analyzer, _anonymizer
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        _analyzer = AnalyzerEngine()
        _anonymizer = AnonymizerEngine()
        logger.info("pii: Presidio engines initialised (en_core_web_lg)")
    except Exception as exc:
        logger.warning(
            "pii: failed to initialise Presidio (%s); PII checks disabled for this session",
            exc,
        )
        return None, None
    return _analyzer, _anonymizer


def redact(text: str) -> tuple[str, bool]:
    """Detect and redact PII from text.

    Returns (redacted_text, pii_found).

    - If no PII found: returns (original_text, False) — no copy.
    - If PII found: returns (anonymised_text, True).
    - On any failure: returns (original_text, False) and logs a warning.
      Never raises.
    """
    if not text or not text.strip():
        return text, False

    analyzer, anonymizer = _get_engines()
    if analyzer is None or anonymizer is None:
        return text, False

    try:
        results = analyzer.analyze(text=text, language="en")
        if not results:
            return text, False

        anonymised = anonymizer.anonymize(text=text, analyzer_results=results)
        entity_types = sorted({r.entity_type for r in results})
        logger.info(
            "pii.redact: redacted %d entity instance(s) — types=%s",
            len(results),
            entity_types,
        )
        return anonymised.text, True
    except Exception as exc:
        logger.warning("pii.redact: anonymisation failed (%s), returning original text", exc)
        return text, False
