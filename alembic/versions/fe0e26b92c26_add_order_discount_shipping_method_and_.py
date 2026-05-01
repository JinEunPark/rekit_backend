"""add order discount/shipping_method and payment card meta

Revision ID: fe0e26b92c26
Revises: e9bcd41ab78f
Create Date: 2026-05-01 14:41:14.031745+09:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fe0e26b92c26"
down_revision: Union[str, None] = "e9bcd41ab78f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("discount_amount", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("orders", "discount_amount", server_default=None)

    op.add_column(
        "orders",
        sa.Column(
            "shipping_method",
            sa.Enum(
                "PARCEL",
                "FREIGHT",
                "DIRECT",
                name="shipmentmethod",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
    )

    op.add_column("payments", sa.Column("card_company", sa.String(length=30), nullable=True))
    op.add_column("payments", sa.Column("card_last4", sa.String(length=4), nullable=True))
    op.add_column("payments", sa.Column("installment_months", sa.Integer(), nullable=True))
    op.add_column("payments", sa.Column("approval_number", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "approval_number")
    op.drop_column("payments", "installment_months")
    op.drop_column("payments", "card_last4")
    op.drop_column("payments", "card_company")
    op.drop_column("orders", "shipping_method")
    op.drop_column("orders", "discount_amount")
