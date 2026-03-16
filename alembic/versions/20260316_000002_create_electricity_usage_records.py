from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260316_000002"
down_revision = "20260316_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "electricity_usage_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("billing_month", sa.String(length=20), nullable=False),
        sa.Column("measured_at", sa.DateTime(), nullable=False),
        sa.Column("usage_kwh", sa.Float(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("csv_path", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "provider_name",
            "account_id",
            "measured_at",
            name="uq_electricity_usage_provider_account_measured_at",
        ),
    )
    op.create_index("ix_electricity_usage_records_id", "electricity_usage_records", ["id"])
    op.create_index(
        "ix_electricity_usage_records_provider_name",
        "electricity_usage_records",
        ["provider_name"],
    )
    op.create_index(
        "ix_electricity_usage_records_account_id",
        "electricity_usage_records",
        ["account_id"],
    )
    op.create_index(
        "ix_electricity_usage_records_billing_month",
        "electricity_usage_records",
        ["billing_month"],
    )
    op.create_index(
        "ix_electricity_usage_records_measured_at",
        "electricity_usage_records",
        ["measured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_electricity_usage_records_measured_at", table_name="electricity_usage_records")
    op.drop_index("ix_electricity_usage_records_billing_month", table_name="electricity_usage_records")
    op.drop_index("ix_electricity_usage_records_account_id", table_name="electricity_usage_records")
    op.drop_index("ix_electricity_usage_records_provider_name", table_name="electricity_usage_records")
    op.drop_index("ix_electricity_usage_records_id", table_name="electricity_usage_records")
    op.drop_table("electricity_usage_records")
