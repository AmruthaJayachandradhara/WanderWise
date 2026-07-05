"""Prompt registry — load, validate, cache, and render versioned prompts.

Prompts live as YAML files under prompts/library/{prompt_id}.yaml.
The path-style prompt_id (e.g. "orchestrator/router_intent") maps directly
to the file path and to the eval-cases path under tests/eval/cases/.

Usage:
    from backend.app.prompts.registry import render, get_prompt

    system_prompt = render("orchestrator/router_intent")
    p = get_prompt("orchestrator/router_intent")  # full PromptDefinition
"""

from functools import lru_cache
from pathlib import Path

import yaml

from .schema import PromptDefinition

LIBRARY_DIR = Path(__file__).parent / "library"


@lru_cache(maxsize=None)
def get_prompt(prompt_id: str) -> PromptDefinition:
    """Load and cache a prompt by its path-style ID (e.g. 'rag/synthesis').

    Raises FileNotFoundError if no prompt is registered at that ID.
    """
    path = LIBRARY_DIR / f"{prompt_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No prompt registered at '{prompt_id}' (looked in {path})")
    return PromptDefinition(**yaml.safe_load(path.read_text()))


def render(prompt_id: str, **kwargs: str) -> str:
    """Load prompt + format template in one call.

    Call-site ergonomics are near-identical to an f-string:
        prompt = render("orchestrator/router_intent")
        prompt = render("weather/argument_extraction", query=query)
    """
    p = get_prompt(prompt_id)
    missing = set(p.input_variables) - set(kwargs)
    if missing:
        raise ValueError(f"Prompt '{prompt_id}' is missing variables: {missing}")
    if not p.input_variables:
        # No variables to substitute — return template as-is.
        # str.format() must not run: prompt templates contain raw JSON examples
        # with {"key": value} syntax that Python's format parser mistakes for
        # format placeholders, raising KeyError on the JSON key names.
        return p.template
    return p.template.format(**kwargs)
