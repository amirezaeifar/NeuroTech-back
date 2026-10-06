"""Operational Flask CLI commands."""

from __future__ import annotations

import click
from flask import Flask, current_app

from app.services.auth import auth_service_from_container
from app.services.seed import seed_academy, seed_catalog_and_events


def register_cli(app: Flask) -> None:
    @app.cli.command("seed-journal")
    def import_journal() -> None:
        """Publish missing bilingual sample articles in development only."""
        from app.services.seed_journal import seed_journal

        try:
            count = seed_journal(current_app.extensions["container"])
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        click.echo(f"Published {count} journal samples; existing articles were preserved.")

    @app.cli.command("seed")
    def seed() -> None:
        """Insert missing baseline content without overwriting existing data."""
        created = seed_academy(current_app.extensions["container"])
        products, events = seed_catalog_and_events(current_app.extensions["container"])
        click.echo(
            "Seed complete; "
            f"{created} course(s), {products} product(s), and {events} event(s) created."
        )

    @app.cli.command("seed-partners")
    def import_partners() -> None:
        """Import original resumes without overwriting existing profiles."""
        from app.services.seed_partners import seed_partners
        count = seed_partners(current_app.extensions["container"])
        click.echo(f"Imported {count} partner profiles.")

    @app.cli.command("bootstrap-admin")
    @click.option("--name", prompt="Display name")
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def bootstrap_admin(name: str, email: str, password: str) -> None:
        """Create the first admin; later elevated accounts require invitations."""
        service = auth_service_from_container(current_app.extensions["container"])
        user = service.bootstrap_admin(name, email, password)
        click.echo(f"Admin created: {user.email}")
