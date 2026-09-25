"""Prepare private, inactive jury credentials outside the source tree."""

import argparse
import os
from pathlib import Path
import re
import secrets
import subprocess


def private_destination(output_dir: Path, web_root: Path) -> Path:
    """Reject both public path spellings and symlink targets before generating secrets."""
    def locations(path: Path) -> tuple[Path, Path]:
        path = path.expanduser()
        return Path(os.path.abspath(path)), path.resolve()

    repository = Path(__file__).resolve().parents[1]
    roots = (repository, Path("/opt/tramflow-backups"), web_root)
    forbidden = [location for root in roots for location in locations(root)]
    site_families = locations(Path("/srv/tramflow"))
    for destination in locations(output_dir):
        if any(destination.is_relative_to(root) for root in forbidden):
            raise ValueError("Credentials must be outside the repository, web roots and deployment backups.")
        for site in site_families:
            if destination.is_relative_to(site.parent):
                parts = destination.relative_to(site.parent).parts
                if parts and parts[0].startswith(site.name):
                    raise ValueError("Credentials cannot be stored under /srv/tramflow*.")
    return output_dir.expanduser().resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caddy", default="caddy")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--host", default="tramflow.ru")
    parser.add_argument("--web-root", type=Path,
                        default=Path(os.environ.get("TRAMFLOW_ROOT") or "/srv/tramflow"),
                        help="Additional static site root to exclude (defaults to TRAMFLOW_ROOT or /srv/tramflow).")
    args = parser.parse_args()
    try:
        destination = private_destination(args.output_dir, args.web_root)
    except ValueError as exc:
        parser.error(str(exc))
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", args.host):
        parser.error("--host must be a hostname, without scheme, port or path.")
    if destination.exists():
        parser.error("Output directory already exists; credentials will not be overwritten.")
    username = "jury-" + secrets.token_hex(4)
    password = secrets.token_urlsafe(24)
    # Stdin avoids putting the password in the process list or shell history.
    result = subprocess.run(
        [args.caddy, "hash-password", "--algorithm", "bcrypt"],
        input=password + "\n", capture_output=True, text=True, check=True,
    )
    password_hash = result.stdout.strip()
    if not re.fullmatch(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", password_hash):
        raise RuntimeError("Caddy did not return a bcrypt hash; no files written.")
    destination.mkdir(mode=0o700, parents=False)
    files = {
        "tramflow-users.caddy": f"{username} {password_hash}\n",
        "jury.netrc": f"machine {args.host}\nlogin {username}\npassword {password}\n",
        "jury-access.txt": (
            "Закрытый материал для жюри. Подготовлен локально, доступ ещё не включён.\n"
            f"Адрес после активации: https://{args.host}/\n"
            f"Логин: {username}\nПароль: {password}\n"
            "Передавать только по отдельно разрешённому закрытому каналу.\n"
            "Не включать в Git, образ, архив решения, презентацию или публичную папку.\n"
            "При предупреждении о сертификате не вводить пароль.\n"
        ),
    }
    for name, content in files.items():
        with os.fdopen(os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
            f.write(content)
    print(f"Private files prepared in {destination}; credentials were not printed or activated.")


if __name__ == "__main__":
    main()
