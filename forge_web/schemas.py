"""Pydantic request/response models for the Forge web API."""

from pydantic import BaseModel


class ConfigUpdateRequest(BaseModel):
    entries: list[dict[str, str]]


class BatchRequest(BaseModel):
    action: str
    ids: list[str]
