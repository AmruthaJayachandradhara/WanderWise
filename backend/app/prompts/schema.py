"""Pydantic model describing the shape of a prompt YAML file."""

from typing import Optional
from pydantic import BaseModel


class PromptEvalConfig(BaseModel):
    dataset: str
    metric: str  # exact_match | schema_valid | llm_judge
    threshold: float


class PromptDefinition(BaseModel):
    prompt_id: str
    version: int
    tier: str  # small | large
    status: str = "active"  # active | experimental | deprecated
    description: str
    template: str
    input_variables: list[str] = []
    output_schema: Optional[dict] = None
    eval: Optional[PromptEvalConfig] = None
    changelog: Optional[list[dict]] = None
