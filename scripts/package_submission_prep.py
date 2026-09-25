"""Package reviewed source paths and a DS status note; never fabricate a submission."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from scripts.check_delivery import local_only


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "README.md", "INTEGRATION.md", "AGENTS.md", "LICENSE", ".gitignore", ".gitattributes",
    "claude-interactive-tram-map.md",
    ".dockerignore", ".env.example", "compose.yaml", "compose.server.yaml",
    "compose.handoff.yaml", "compose.load.yaml",
    "frontend/README.md", "frontend/package.json", "frontend/package-lock.json", "frontend/index.html",
    "frontend/tsconfig.json", "frontend/vite.config.js",
    "frontend/public/map-local/network.json", "data/README.md",
    "ml/reports/experiment-log.csv",
)
SOURCE_DIRS = (
    "backend", "ml", "frontend/src", "frontend/scripts", "scripts", "tests",
    "docs", "deploy", ".github",
)
EXTENSIONS = {".py", ".js", ".cjs", ".mjs", ".tsx", ".ts", ".css", ".md", ".json", ".yml", ".yaml", ".sh"}
SPECIAL_NAMES = {"requirements.txt", "requirements.in", "Dockerfile", "frontend.Dockerfile",
                 "Caddyfile.http", "Caddyfile.https", "Caddyfile.protected"}


def write_archive(archive: Path, prefix: str, sources: dict[str, bytes]) -> None:
    """Identical source bytes produce an identical ZIP, independent of wall time."""
    manifest = "".join(f"{hashlib.sha256(content).hexdigest()}  {name}\n"
                       for name, content in sorted(sources.items())).encode()
    with ZipFile(archive, "x", compression=ZIP_DEFLATED) as z:
        for name, content in sorted({**sources, "MANIFEST.sha256": manifest}.items()):
            info = ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            z.writestr(info, content)


def verify_archive(archive: Path, prefix: str, sources: dict[str, bytes]) -> dict:
    """Check actual archive bytes; integrity is not product or submission acceptance."""
    with ZipFile(archive) as z:
        expected = {prefix + name for name in sources} | {prefix + "MANIFEST.sha256"}
        if z.testzip() is not None or set(z.namelist()) != expected or len(z.namelist()) != len(expected):
            raise RuntimeError(f"Archive integrity or file list mismatch: {archive.name}")
        manifest = "".join(f"{hashlib.sha256(content).hexdigest()}  {name}\n"
                           for name, content in sorted(sources.items()))
        if z.read(prefix + "MANIFEST.sha256") != manifest.encode():
            raise RuntimeError(f"Archive manifest mismatch: {archive.name}")
        for name, source in sources.items():
            if z.read(prefix + name) != source:
                raise RuntimeError(f"Archived source mismatch: {name}")
    return {"files": len(sources), "bytes": archive.stat().st_size,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ml-git-dir", type=Path)
    parser.add_argument("--ml-ref", help="Reviewed immutable 40-character commit SHA")
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    if destination.exists():
        parser.error("Use a new output directory; existing artifacts are not overwritten.")
    if bool(args.ml_git_dir) != bool(args.ml_ref):
        parser.error("--ml-git-dir and --ml-ref must be provided together.")
    ml_files = {}
    if args.ml_ref:
        if not re.fullmatch(r"[0-9a-f]{40}", args.ml_ref):
            parser.error("--ml-ref must be a reviewed commit SHA, not a moving branch.")
        git = ["git", "--git-dir=" + str(args.ml_git_dir.resolve())]
        names = subprocess.check_output(git + ["ls-tree", "-r", "--name-only", args.ml_ref], text=True).splitlines()
        for name in names:
            path = Path(name)
            is_source = not local_only(name) and name.startswith(("ml/", "tests/ml/")) and (
                path.suffix in {".py", ".md", ".json"} or name in {
                    "ml/requirements.txt", "ml/external-sources.json", "ml/examples/batch-request.json",
                    "ml/examples/batch-output.json", "ml/reports/experiment-log.csv",
                }
            )
            if is_source or name in {"LICENSE", "backend/requirements.txt"}:
                ml_files[name] = subprocess.check_output(git + ["show", args.ml_ref + ":" + name])
        if "ml/reports/model-card.md" not in ml_files:
            parser.error("Reviewed ML model card is missing from the selected commit.")
        ml_files["REVIEW-README.md"] = (
            "# ML-кандидат для проверки, не готовая DS-сдача\n\n"
            f"Источник: MISISion-Possible/tram-forecast, commit {args.ml_ref}.\n"
            "Сохранён код из указанного commit. Веса, raw, sample и submission отсутствуют.\n"
            "Возможности и результаты этой версии проверяйте по включённым README и model-card;\n"
            "выбор commit сам по себе не подтверждает готовность модели или совпадение с web release.\n"
            "Перед сдачей проверить train-маску, временные границы, округление и preflight.\n"
            "По письменному ответу сохраняем исходный sample с № 5; нулевой fallback учитывается метрикой.\n"
            "Установка ML-зависимостей: python -m pip install -r ml/requirements.txt.\n"
            "Команды автора и ограничения: ml/README.md.\n"
        ).encode()
    # Never sweep local/untracked JSON or notes into a distributable archive.
    tracked = {name.decode() for name in subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--cached"]).split(b"\0") if name}
    source_commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    source_dirty = bool(subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"]))
    required = {*ROOT_FILES, "frontend/Dockerfile"}
    missing = required - tracked
    if missing:
        parser.error("Required sources must be included in Git: " + ", ".join(sorted(missing)))
    paths = {ROOT / name for name in required}
    for name in tracked:
        path = Path(name)
        if local_only(name):
            parser.error("Local data/artifact cannot be packaged: " + name)
        if any(name.startswith(dirname + "/") for dirname in SOURCE_DIRS):
            if path.suffix in EXTENSIONS or path.name in SPECIAL_NAMES:
                paths.add(ROOT / path)
    files = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise RuntimeError(f"Refusing a source symlink/outside path: {path.name}")
        if path.name in {"jury-access.txt", "tramflow-users.caddy"} or path.suffix == ".netrc":
            raise RuntimeError("Private credentials cannot be packaged.")
        files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    note = (
        "# Локальный комплект подготовки, не финальная сдача\n\n"
        f"Базовый HEAD: {source_commit}; tracked working changes: {source_dirty}.\n"
        "Web использует /api/v2/handoff/*: готовый ML CSV, день/неделя/месяц и закреплённый экспорт.\n"
        "Сам ML-пакет передаётся отдельно: без него интерфейс сообщает недоступность прогноза.\n"
        "Исходники — текущие байты файлов, включённых в индекс Git; untracked-файлы не включены.\n"
        "Незакоммиченные изменения отслеживаемых файлов также попадают в архив; проверьте MANIFEST.sha256.\n"
        "Начать с README.md и docs/integration/qa-2026-09-25/jury-guide.md.\n"
        "Импорт: python -m backend.handoff.install /absolute/path/package.zip --output artifacts/release.\n"
        "После установки backend-зависимостей и импорта: export TRAMFLOW_HANDOFF_HOST_DIR=\"$PWD/artifacts/release\";\n"
        "docker compose -f compose.yaml -f compose.handoff.yaml up --build. Первая сборка требует сети/кэша.\n"
        "Качество/нагрузка и их версии: ml/reports/model-card.md и docs/verification-load.md.\n"
        "Raw, модель, private credentials и DS submission не включены.\n"
        "Публикация, commit/push и отправка выполняются отдельно.\n"
    ).encode()
    files["PREPARATION-README.md"] = note
    destination.mkdir(parents=True)
    archive = destination / "web-handoff-preparation.zip"
    write_archive(archive, "tram-forecast/", files)
    verification = {archive.name: verify_archive(archive, "tram-forecast/", files)}
    outputs = [archive]
    if ml_files:
        ml_archive = destination / "ds-ml-candidate-review.zip"
        write_archive(ml_archive, "ml-review/", ml_files)
        outputs.append(ml_archive)
        verification[ml_archive.name] = verify_archive(ml_archive, "ml-review/", ml_files)
    (destination / "ds-status.md").write_text(
        "# DS передаётся отдельным локальным комплектом\n\n"
        "Этот упаковщик не ищет, не создаёт и не включает реальный submission, sample или веса.\n"
        "Наличие готового DS-файла на машине проверяется отдельно; отчёты прошлых версий не заменяют preflight.\n"
        "Для выбранной модели выполнить ml submission по ML README и проверить checksum результата.\n"
        "Сохраняем полный исходный sample: 14 640 строк, № 5, ночь, точные ключи и порядок.\n"
        "Это файл статуса, его нельзя загружать вместо конкурсного CSV.\n"
        "Опись: tram-forecast/docs/integration/qa-2026-09-25/release-checklist.md в web-архиве.\n"
    )
    (destination / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
        for p in [*outputs, destination / "ds-status.md"]
    ))
    (destination / "verification.json").write_text(json.dumps({
        "status": "preparation_only",
        "scope": "archive_integrity_only",
        "checks": ["ZIP CRC", "exact file lists", "per-file manifests", "source bytes"],
        "archives": verification,
        "source_commit": source_commit,
        "source_dirty": source_dirty,
        "ml_source_commit": args.ml_ref,
        "not_performed_by_packager": ["deployment", "messages", "commit", "push", "actual DS submission",
                                      "final owner acceptance", "real-model backtest", "HTTP load test"],
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"Prepared {len(files)} public source/document files in {archive}")
    print("No actual DS submission or private credentials packaged; ML sources, if included, are for review.")


if __name__ == "__main__":
    main()
