"""Import bundled bilingual profiles once without replacing administrator edits."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.content_models import PartnerProfile, PartnerTranslation


def seed_partners(container):
    records = json.loads(
        (Path(__file__).parents[1] / "data" / "partners.json").read_text(encoding="utf-8")
    )
    created = 0
    with container.database.session() as session:
        for record in records:
            if session.scalar(
                select(PartnerProfile.id).where(PartnerProfile.slug == record["slug"])
            ):
                continue
            partner = PartnerProfile(
                slug=record["slug"], position=record["position"], published_at=datetime.now(UTC)
            )
            partner.translations = [PartnerTranslation(**item) for item in record["translations"]]
            session.add(partner)
            created += 1
        session.commit()
    return created
