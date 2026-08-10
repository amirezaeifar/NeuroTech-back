def test_architecture_packages_are_importable() -> None:
    import app
    import app.bootstrap
    import app.core
    import app.core.config
    import app.core.container
    import app.domain
    import app.routes
    import app.services

    assert app.__name__ == "app"
