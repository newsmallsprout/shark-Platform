"""从 GEOIP_DATABASE_URL 下载 GeoLite2-City.mmdb.gz 并解压（须遵守 MaxMind EULA）。"""

from django.core.management.base import BaseCommand

from observability.geoip import ensure_database_file, geoip_database_path, geoip_mirror_url


class Command(BaseCommand):
    help = "Download GeoLite2-City database from GEOIP_DATABASE_URL mirror"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download even if .mmdb already exists",
        )

    def handle(self, *args, **opts):
        path = geoip_database_path()
        self.stdout.write(f"GeoIP target file: {path}")
        self.stdout.flush()

        url = geoip_mirror_url()
        if not url:
            if path.exists() and path.stat().st_size > 1_048_576:
                self.stdout.write(
                    self.style.SUCCESS(
                        "GEOIP_DATABASE_URL unset — using existing file (e.g. bind-mount from host)."
                    )
                )
                return
            self.stderr.write(
                "Set GEOIP_DATABASE_URL to a .mmdb.gz mirror, or mount GeoLite2-City.mmdb "
                "(docker-compose: GEOIP_MMDB_HOST_FILE → /app/state/GeoLite2-City.mmdb)."
            )
            return

        def _progress(msg: str) -> None:
            self.stdout.write(msg)
            self.stdout.flush()

        ok = ensure_database_file(force=opts["force"], progress=_progress)
        if ok and path.exists():
            self.stdout.write(self.style.SUCCESS(f"GeoIP database ready: {path}"))
        else:
            self.stderr.write(f"Failed or missing file at {path}")
