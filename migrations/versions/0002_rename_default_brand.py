"""Rename the default brand from SecureDrop to Ratatosk (COMP-007).

Only installs still showing the old *default* brand name are changed; a brand
an admin chose themselves is left alone.

Revision ID: 0002_rename_default_brand
Revises: 0001_baseline
"""
from alembic import op

revision = "0002_rename_default_brand"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE system_settings SET brand_name = 'Ratatosk', version = version + 1 WHERE brand_name = 'SecureDrop'")
    op.execute("UPDATE system_settings SET smtp_from_name = 'Ratatosk' WHERE smtp_from_name = 'SecureDrop'")


def downgrade() -> None:
    op.execute("UPDATE system_settings SET brand_name = 'SecureDrop', version = version + 1 WHERE brand_name = 'Ratatosk'")
