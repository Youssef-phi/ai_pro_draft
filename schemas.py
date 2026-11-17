"""Structured outputs shared by every agent (Pydantic).

Models are deliberately forgiving about shape (small local models are sloppy) and
strict about meaning: claim labels are decided by code in agents/base.py, not by the model.
"""
from __future__ import annotations

import json
import types
import typing
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMOTIONS = ("happy", "excited", "thinking", "skeptical", "worried", "stern", "neutral")
VERDICTS = ("go", "repeat", "pivot", "stop")


class Claim(BaseModel):
    text: str
    source_url: Optional[str] = None
    label: Literal["SOURCED", "ASSUMPTION"] = "ASSUMPTION"

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, value):
        if isinstance(value, str):
            return {"text": value}
        if isinstance(value, dict):
            value = dict(value)
            value["text"] = str(value.get("text") or value.get("claim") or "")
            if str(value.get("label", "")).upper() not in ("SOURCED", "ASSUMPTION"):
                value["label"] = "ASSUMPTION"
            else:
                value["label"] = str(value["label"]).upper()
            url = value.get("source_url") or value.get("url")
            value["source_url"] = str(url) if url else None
        return value


def _flatten(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten(v) for v in value)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_flatten(v)}" for k, v in value.items())
    return "" if value is None else str(value)


class AgentOutput(BaseModel):
    """Fields every agent returns."""
    model_config = ConfigDict(extra="ignore")

    speech: str = Field("", description="One or two short spoken sentences for the boardroom, plain words")
    emotion: str = Field("neutral", description="one of: " + ", ".join(EMOTIONS))
    claims: list[Claim] = Field(default_factory=list, description=(
        'factual or market claims you rely on: [{"text": "...", "source_url": "<a URL copied exactly from '
        'the evidence you were given, or null>", "label": "SOURCED" or "ASSUMPTION"}]'))
    artifacts: list[str] = Field(default_factory=list, description="leave empty; the system fills this in")

    @model_validator(mode="before")
    @classmethod
    def _coerce_shapes(cls, data):
        """Accept a string where a list is expected and the other way round."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for name, info in cls.model_fields.items():
            if name not in data or data[name] is None:
                data.pop(name, None)
                continue
            annotation, value = info.annotation, data[name]
            origin = typing.get_origin(annotation)
            if origin in (typing.Union, types.UnionType):
                args = [a for a in typing.get_args(annotation) if a is not type(None)]
                annotation = args[0] if args else annotation
                origin = typing.get_origin(annotation)
            if annotation is str and not isinstance(value, str):
                data[name] = _flatten(value)
            elif origin is list:
                if isinstance(value, (str, dict)):
                    value = [value]
                inner = (typing.get_args(annotation) or (None,))[0]
                if inner is str and isinstance(value, list):
                    value = [_flatten(v) for v in value]
                data[name] = value
            elif annotation is float and isinstance(value, str):
                try:
                    data[name] = float("".join(ch for ch in value if ch.isdigit() or ch == ".") or 0)
                except ValueError:
                    data[name] = 0.0
        return data

    @field_validator("emotion", mode="after")
    @classmethod
    def _emotion(cls, value: str) -> str:
        value = (value or "").strip().lower()
        return value if value in EMOTIONS else "neutral"


def schema_hint(model: type[BaseModel]) -> str:
    """A plain description of the JSON an agent must return."""
    lines = ["Return ONE JSON object with exactly these keys:"]
    for name, info in model.model_fields.items():
        if name == "artifacts":
            continue
        lines.append(f'- "{name}": {info.description or ""}')
    return "\n".join(lines)


def compact(value, limit: int = 6000) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]
