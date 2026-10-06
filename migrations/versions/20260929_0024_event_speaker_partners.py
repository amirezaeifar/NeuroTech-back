"""Allow a published partner profile to appear as an event speaker."""

import sqlalchemy as sa
from alembic import op

revision = "20260929_0024"
down_revision = "20260928_0023"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("event_speakers") as batch:
        batch.alter_column("user_id", existing_type=sa.Uuid(as_uuid=True, native_uuid=False), nullable=True)
        batch.add_column(sa.Column("partner_id", sa.Uuid(as_uuid=True, native_uuid=False), nullable=True))
        batch.create_foreign_key("fk_event_speaker_partner", "partner_profiles", ["partner_id"], ["id"])
        batch.create_unique_constraint("uq_event_speaker_partner", ["event_id", "partner_id"])
        batch.create_index("ix_event_speakers_partner_id", ["partner_id"])


def downgrade():
    with op.batch_alter_table("event_speakers") as batch:
        batch.drop_index("ix_event_speakers_partner_id")
        batch.drop_constraint("uq_event_speaker_partner", type_="unique")
        batch.drop_constraint("fk_event_speaker_partner", type_="foreignkey")
        batch.drop_column("partner_id")
        batch.alter_column("user_id", existing_type=sa.Uuid(as_uuid=True, native_uuid=False), nullable=False)
