"""Unit tests for the shared JSON-parsing helper (Phase 4 TODO cleanup).

parse_json_dict() must never raise — every call site relies on it
degrading to a safe default instead of letting JSONDecodeError, TypeError,
or a raw KeyError from a mis-shaped payload escape into the graph.
"""

from backend.app.llm.parsing import parse_json_dict


def test_valid_dict_passthrough():
    assert parse_json_dict('{"a": 1}') == {"a": 1}


def test_invalid_json_returns_default():
    assert parse_json_dict("not json{", default={"x": 1}) == {"x": 1}


def test_invalid_json_returns_empty_dict_by_default():
    assert parse_json_dict("not json{") == {}


def test_non_dict_json_scalar_returns_default():
    # A bare JSON string — valid JSON, but not the object shape callers need.
    assert parse_json_dict('"injection"', default={"y": 2}) == {"y": 2}


def test_non_dict_json_list_returns_default():
    assert parse_json_dict("[1, 2, 3]") == {}


def test_none_input_returns_default():
    assert parse_json_dict(None, default={"z": 3}) == {"z": 3}


def test_default_is_not_mutated_by_caller():
    shared_default = {"a": 1}
    result = parse_json_dict("not json", default=shared_default)
    result["a"] = 999
    assert shared_default == {"a": 1}
