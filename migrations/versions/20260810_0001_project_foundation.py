"""Create the project foundation migration.

Revision ID: 20260810_0001
Revises:
Create Date: 2026-08-10
"""

from collections.abc import Sequence

revision: str = "20260810_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Establish the first migration boundary; domain tables follow in later stages."""


def downgrade() -> None:
    """The foundation migration does not create database objects."""
