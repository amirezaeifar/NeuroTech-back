"""Operational Flask CLI commands."""

from __future__ import annotations

import click
from flask import Flask, current_app

from app.services.auth import auth_service_from_container
from app.services.seed import seed_academy


def register_cli(app: Flask) -> None:
    @app.cli.command("seed")
    def seed() -> None:
        """Insert missing baseline content without overwriting existing data."""
        created = seed_academy(current_app.extensions["container"])
        click.echo(f"Seed complete; {created} course(s) created.")

    @app.cli.command("bootstrap-admin")
    @click.option("--name", prompt="Display name")
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def bootstrap_admin(name: str, email: str, password: str) -> None:
        """Create the first admin; later elevated accounts require invitations."""
        service = auth_service_from_container(current_app.extensions["container"])
        user = service.bootstrap_admin(name, email, password)
        click.echo(f"Admin created: {user.email}")
