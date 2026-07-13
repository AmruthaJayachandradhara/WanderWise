"""Unit tests for Presidio-based PII redaction (backend/app/guardrails/pii.py).

Uses the real Presidio AnalyzerEngine/AnonymizerEngine (spaCy en_core_web_lg)
— not mocked — since the entity-scoping behavior under test (LOCATION/NRP/
DATE_TIME exclusion) is a property of the real analyzer's registered
recognizers, not something a mock could meaningfully stand in for. The first
call in this module pays the ~2s spaCy load cost once; pii.py's own
module-level globals cache it for the rest of the run.
"""

import pytest

from backend.app.guardrails.pii import _EXCLUDED_ENTITIES, redact


class TestTruePiiStillRedacted:
    @pytest.mark.parametrize("text,placeholder,secret", [
        ("My email is jane.doe@example.com.", "<EMAIL_ADDRESS>", "jane.doe@example.com"),
        ("Call me at 415-555-1234.", "<PHONE_NUMBER>", "415-555-1234"),
        ("My card number is 4111 1111 1111 1111.", "<CREDIT_CARD>", "4111 1111 1111 1111"),
        ("My name is John Smith.", "<PERSON>", "John Smith"),
    ])
    def test_redacted(self, text, placeholder, secret):
        redacted, found = redact(text)
        assert found is True
        assert placeholder in redacted
        assert secret not in redacted


class TestUsPassportRedacted:
    def test_passport_number_redacted(self):
        redacted, found = redact("My passport number is 923456789.")
        assert found is True
        assert "<US_PASSPORT>" in redacted
        assert "923456789" not in redacted


class TestNonPiiEntitiesSurvive:
    def test_location_not_redacted(self):
        text = "Plan a trip to Tokyo, Japan next month."
        redacted, found = redact(text)
        assert "Tokyo" in redacted
        assert "Japan" in redacted
        assert "<LOCATION>" not in redacted

    def test_nationality_not_redacted(self):
        text = "I have an Indian passport, book me a flight to Paris."
        redacted, found = redact(text)
        assert "Indian" in redacted
        assert "Paris" in redacted
        assert "<NRP>" not in redacted
        assert "<LOCATION>" not in redacted

    def test_relative_date_not_redacted(self):
        text = "Book a flight to Rome next month."
        redacted, found = redact(text)
        assert "next month" in redacted
        assert "<DATE_TIME>" not in redacted


class TestEmptyInput:
    def test_empty_string(self):
        assert redact("") == ("", False)

    def test_whitespace_only(self):
        assert redact("   ") == ("   ", False)


class TestGracefulDegradation:
    def test_presidio_init_failure_returns_original_text(self, monkeypatch):
        import backend.app.guardrails.pii as pii_module

        monkeypatch.setattr(pii_module, "_analyzer", None)
        monkeypatch.setattr(pii_module, "_anonymizer", None)
        monkeypatch.setattr(pii_module, "_active_entities", None)
        monkeypatch.setattr(pii_module, "_get_engines", lambda: (None, None, None))

        redacted, found = pii_module.redact("My email is jane.doe@example.com.")
        assert redacted == "My email is jane.doe@example.com."
        assert found is False


class TestEntityDenylist:
    def test_excluded_entities_are_real_presidio_types(self):
        from presidio_analyzer import AnalyzerEngine

        supported = set(AnalyzerEngine().get_supported_entities())
        assert _EXCLUDED_ENTITIES <= supported
