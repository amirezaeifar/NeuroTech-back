"""Download the current free DB-IP Country Lite database.

DB-IP requires attribution on any page that displays the resulting country data.
"""

from __future__ import annotations

import gzip
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> None:
    destination = Path(os.getenv("GEOIP_DATABASE_PATH", "storage/dbip-country-lite.mmdb"))
    month = datetime.now(UTC).strftime("%Y-%m")
    filename = f"dbip-country-lite-{month}.mmdb.gz"
    archive = None
    last_error = None
    for base in ("https://download.db-ip.com/free", "https://dbip.mirror.framasoft.org/files"):
        try:
            request = Request(f"{base}/{filename}", headers={"User-Agent": "NeuroTech-GeoIP-Updater/1.0"})
            with urlopen(request, timeout=45) as response:
                archive = response.read(30_000_001)
            break
        except (HTTPError, URLError) as error:
            last_error = error
    if archive is None:
        raise RuntimeError("The DB-IP database could not be downloaded.") from last_error
    if len(archive) > 30_000_000:
        raise RuntimeError("DB-IP download exceeded the expected size.")
    database = gzip.decompress(archive)
    if len(database) > 100_000_000:
        raise RuntimeError("DB-IP database exceeded the expected size.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".mmdb.tmp")
    temporary.write_bytes(database)
    import maxminddb

    with maxminddb.open_database(str(temporary)) as reader:
        if not reader.get("8.8.8.8"):
            raise RuntimeError("The downloaded country database is invalid.")
    temporary.replace(destination)
    print(f"Updated {destination}")


if __name__ == "__main__":
    main()
