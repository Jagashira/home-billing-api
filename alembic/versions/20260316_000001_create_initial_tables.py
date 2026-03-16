from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260316_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_type", sa.String(length=50), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("billing_month", sa.String(length=20), nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("usage_period", sa.String(length=255), nullable=True),
        sa.Column("payment_status", sa.String(length=100), nullable=True),
        sa.Column("detail_url", sa.String(length=500), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("raw_data_json", sa.Text(), nullable=True),
        sa.Column("raw_snapshot_path", sa.String(length=500), nullable=True),
        sa.Column("screenshot_path", sa.String(length=500), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "service_type",
            "provider_name",
            "account_id",
            "billing_month",
            name="uq_billing_records_provider_account_month",
        ),
    )
    op.create_index("ix_billing_records_id", "billing_records", ["id"])
    op.create_index("ix_billing_records_service_type", "billing_records", ["service_type"])
    op.create_index("ix_billing_records_provider_name", "billing_records", ["provider_name"])
    op.create_index("ix_billing_records_account_id", "billing_records", ["account_id"])
    op.create_index("ix_billing_records_billing_month", "billing_records", ["billing_month"])
    op.create_index("ix_billing_records_fetched_at", "billing_records", ["fetched_at"])

    op.create_table(
        "fetch_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("screenshot_path", sa.String(length=500), nullable=True),
        sa.Column("html_snapshot_path", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_fetch_logs_id", "fetch_logs", ["id"])
    op.create_index("ix_fetch_logs_provider_name", "fetch_logs", ["provider_name"])
    op.create_index("ix_fetch_logs_started_at", "fetch_logs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_fetch_logs_started_at", table_name="fetch_logs")
    op.drop_index("ix_fetch_logs_provider_name", table_name="fetch_logs")
    op.drop_index("ix_fetch_logs_id", table_name="fetch_logs")
    op.drop_table("fetch_logs")

    op.drop_index("ix_billing_records_fetched_at", table_name="billing_records")
    op.drop_index("ix_billing_records_billing_month", table_name="billing_records")
    op.drop_index("ix_billing_records_account_id", table_name="billing_records")
    op.drop_index("ix_billing_records_provider_name", table_name="billing_records")
    op.drop_index("ix_billing_records_service_type", table_name="billing_records")
    op.drop_index("ix_billing_records_id", table_name="billing_records")
    op.drop_table("billing_records")

