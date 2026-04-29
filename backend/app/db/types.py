"""Reusable SQL types: pgvector + JSONB + arrays helpers."""

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field

from app.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim


def embedding_field(nullable: bool = True, dim: int | None = None) -> Any:
    return Field(
        default=None,
        sa_column=Column(Vector(dim or EMBEDDING_DIM), nullable=nullable),
    )


def json_field(default: Any = None, nullable: bool = True) -> Any:
    return Field(
        default=default,
        sa_column=Column(JSONB, nullable=nullable),
    )


def str_array_field(default: list | None = None, nullable: bool = True) -> Any:
    return Field(
        default=default,
        sa_column=Column(ARRAY(String), nullable=nullable),
    )
