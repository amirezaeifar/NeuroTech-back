"""Publish the requested bilingual development samples without replacing edits."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.auth_models import User
from app.core.governance_models import BlogPost, BlogPostTranslation


def seed_journal(container):
    if container.settings.environment != "development":
        raise ValueError("Journal samples are only available in development.")
    records = json.loads(
        (Path(__file__).parents[1] / "data" / "journal_samples.json").read_text(encoding="utf-8")
    )
    created = 0
    with container.database.session() as session:
        author = session.scalar(
            select(User)
            .where(
                User.role.in_(["super_admin", "admin"]),
                User.status == "active",
                User.archived_at.is_(None),
            )
            .order_by(User.created_at)
        )
        if author is None:
            raise ValueError("An existing active administrator is required to own the samples.")
        now = datetime.now(UTC)
        for index, record in enumerate(records):
            if session.scalar(select(BlogPost.id).where(BlogPost.slug == record["slug"])):
                continue
            post = BlogPost(
                slug=record["slug"],
                category=record["category"],
                author_user_id=author.id,
                cover_url=record["cover_url"],
                cover_alt=record["cover_alt"],
                created_at=now - timedelta(microseconds=index),
                published_at=now,
            )
            post.translations = [BlogPostTranslation(**item) for item in record["translations"]]
            session.add(post)
            created += 1
        session.commit()
    return created
