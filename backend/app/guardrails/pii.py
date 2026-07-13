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

Entity scoping: Presidio's full default recognizer set also includes
LOCATION, NRP (nationality/religious/political affiliation), and DATE_TIME
— none of which are actually PII in this app's domain. A travel query IS
destination names, nationalities (for visa lookups), and dates (for
flight/hotel search); redacting them corrupts the query text before
router/decompose/RAG/travel-search ever see it (input_guardrail_node
overwrites state["query"] with the redacted text — there is no separate
raw-query field, so this corruption is otherwise permanent for the rest of
the graph run). These three are excluded via _EXCLUDED_ENTITIES below.
Everything else Presidio recognizes stays protected — including
US_PASSPORT, US_SSN, US_BANK_NUMBER, IBAN_CODE, US_DRIVER_LICENSE,
UK_NHS, MEDICAL_LICENSE, CRYPTO, IP_ADDRESS, MAC_ADDRESS, URL — all
realistic sensitive data a user might paste into a visa-focused travel
app. Excluding by denylist (not a hardcoded allowlist) means any entity
type Presidio adds in a future version is redacted by default, not
silently skipped.
"""

import logging

logger = logging.getLogger(__name__)

# Lazy-loaded Presidio engines — heavy: spaCy model load takes ~2s on first call
_analyzer = None
_anonymizer = None
_active_entities: list[str] | None = None

# Full default Presidio entity set as of implementation time (for reference):
# CREDIT_CARD, CRYPTO, DATE_TIME, EMAIL_ADDRESS, IBAN_CODE, IP_ADDRESS,
# LOCATION, MAC_ADDRESS, MEDICAL_LICENSE, NRP, PERSON, PHONE_NUMBER, UK_NHS,
# URL, US_BANK_NUMBER, US_DRIVER_LICENSE, US_ITIN, US_PASSPORT, US_SSN.
_EXCLUDED_ENTITIES: frozenset[str] = frozenset({"LOCATION", "NRP", "DATE_TIME"})


def _get_engines():
    global _analyzer, _anonymizer, _active_entities
    if _analyzer is not None:
        return _analyzer, _anonymizer, _active_entities
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        _analyzer = AnalyzerEngine()
        _anonymizer = AnonymizerEngine()
        _active_entities = sorted(set(_analyzer.get_supported_entities()) - _EXCLUDED_ENTITIES)
        logger.info(
            "pii: Presidio engines initialised (en_core_web_lg); active_entities=%s",
            _active_entities,
        )
    except Exception as exc:
        logger.warning(
            "pii: failed to initialise Presidio (%s); PII checks disabled for this session",
            exc,
        )
        return None, None, None
    return _analyzer, _anonymizer, _active_entities


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

    analyzer, anonymizer, active_entities = _get_engines()
    if analyzer is None or anonymizer is None:
        return text, False

    try:
        results = analyzer.analyze(text=text, language="en", entities=active_entities)
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
