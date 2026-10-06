"""Run an isolated, seeded backend for browser verification; never uses the real DB."""

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parents[1]))


def main():
    with TemporaryDirectory(prefix="neurotech-browser-") as directory:
        os.environ.update(
            APP_ENV="testing",
            TEST_DATABASE_URL=f"sqlite+pysqlite:///{directory}/test.db",
            SECRET_KEY="isolated-browser-test-secret",
            SMS_PROVIDER="fake",
            PAYMENT_PROVIDER="fake",
            UPLOAD_ROOT=f"{directory}/uploads",
            CORS_ORIGINS="http://127.0.0.1:5174",
            FRONTEND_URL="http://127.0.0.1:5174",
        )
        from app import create_app
        from app.core.models import Base
        from app.services.seed import seed_academy, seed_catalog_and_events
        from app.services.seed_partners import seed_partners
        from tests.api.test_content_management import _admin

        app = create_app("testing")
        container = app.extensions["container"]
        Base.metadata.create_all(container.database.engine)
        seed_academy(container)
        seed_catalog_and_events(container)
        seed_partners(container)
        client = app.test_client()
        headers = _admin(client, app)
        cookie = client.get_cookie("access_token_cookie")
        cookie_file = Path(sys.argv[1])
        cookie_file.write_text(
            json.dumps({"access": cookie.value, "csrf": headers["X-CSRF-TOKEN"]})
        )
        try:
            app.run(host="127.0.0.1", port=5001, use_reloader=False)
        finally:
            cookie_file.unlink(missing_ok=True)
            container.database.dispose()


if __name__ == "__main__":
    main()
