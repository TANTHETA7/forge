"""Shared API-layer response schemas.

Purpose:       Pydantic models that define the HTTP contract, kept separate from
                domain models so a domain change doesn't silently change the wire
                format (and vice versa).
Responsibility: Serialization shape only — no behavior.
Depends on:    pydantic.
Depended on by: api/health.py, and every future router.
"""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Wire format for `GET /health`."""

    state: str = Field(..., examples=["ok"])
    app_name: str = Field(..., examples=["Forge"])
    version: str = Field(..., examples=["0.1.0"])
