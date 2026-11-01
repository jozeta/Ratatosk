"""OIDC single sign-on identity columns (FEAT-010).

Revision ID: 0004_oidc
Revises: 0003_e2e_keys_requests
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_oidc"
down_revision = "0003_e2e_keys_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("oidc_issuer", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("oidc_subject", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("password_login", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.create_index(batch_op.f("ix_users_oidc_subject"), ["oidc_subject"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_oidc_subject"))
        batch_op.drop_column("password_login")
        batch_op.drop_column("oidc_subject")
        batch_op.drop_column("oidc_issuer")
