"""Package reviewed source paths and a DS status note; never fabricate a submission."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "README.md", "INTEGRATION.md", "AGENTS.md", "LICENSE", ".gitignore",
    ".dockerignore", ".env.example", "compose.yaml", "compose.server.yaml",
    "frontend/README.md", "frontend/package.json", "frontend/package-lock.json", "frontend/index.html",
    "frontend/tsconfig.json", "frontend/vite.config.js",
    "frontend/public/map-local/network.json", "data/README.md",
    "ml/reports/experiment-log.csv",
)
SOURCE_DIRS = (
    "backend", "ml", "frontend/src", "frontend/scripts", "scripts", "tests",
    "docs", "deploy", ".github",
)
EXTENSIONS = {".py", ".cjs", ".mjs", ".tsx", ".ts", ".css", ".md", ".json", ".yml", ".yaml", ".sh"}
SPECIAL_NAMES = {"requirements.txt", "requirements.in", "Dockerfile", "frontend.Dockerfile",
                 "Caddyfile.http", "Caddyfile.https", "Caddyfile.protected"}


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
            is_source = name.startswith(("ml/", "tests/ml/")) and (
                path.suffix in {".py", ".md"} or name in {
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
            "Сохранён код автора из указанного commit; HTTP web остаётся synthetic. Веса, raw и sample отсутствуют.\n"
            "Эта версия использует полный набор десяти маршрутов и оценивает прогноз до округления.\n"
            "Перед сдачей сверить исходный sample и закрыть GH-02..04: train-маска, округление, временные границы.\n"
            "По письменному ответу сохраняем исходный sample с № 5; нулевой fallback учитывается метрикой.\n"
            "Установка ML-зависимостей: python -m pip install -r ml/requirements.txt.\n"
            "Команды автора и ограничения: ml/README.md.\n"
        ).encode()
    paths = {ROOT / name for name in ROOT_FILES}
    paths.add(ROOT / "frontend/Dockerfile")
    for dirname in SOURCE_DIRS:
        for path in (ROOT / dirname).rglob("*"):
            if not path.is_file() or any(part.startswith(".") or part == "__pycache__"
                                         for part in path.relative_to(ROOT / dirname).parts):
                continue
            if path.suffix in EXTENSIONS or path.name in SPECIAL_NAMES:
                paths.add(path)
    files = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise RuntimeError(f"Refusing a source symlink/outside path: {path.name}")
        if path.name in {"jury-access.txt", "tramflow-users.caddy"} or path.suffix == ".netrc":
            raise RuntimeError("Private credentials cannot be packaged.")
        files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    note = (
        "# Локальный комплект подготовки, не финальная сдача\n\n"
        "Режим web: synthetic v1. Подключённого real-прогноза и HTTP-замеров нет.\n"
        "Отдельные ML-отчёты автора и их ограничения описаны в github-review.md.\n"
        "Включение Basic Auth на VPS и передача данных входа ещё не выполнены.\n"
        "Исходники взяты из текущего рабочего дерева, включая незакоммиченные изменения.\n"
        "Начать с docs/integration/qa-2026-09-25/README.md и jury-guide.md.\n"
        "Сборка: docker compose up --build; первая сборка требует сети/кэша.\n"
        "Raw, модель, private credentials и DS submission не включены.\n"
        "Публикация, commit/push и отправка выполняются отдельно.\n"
    ).encode()
    files["PREPARATION-README.md"] = note
    manifest = "".join(f"{hashlib.sha256(content).hexdigest()}  {name}\n"
                       for name, content in sorted(files.items()))
    destination.mkdir(parents=True)
    archive = destination / "web-synthetic-preparation.zip"
    with ZipFile(archive, "x", compression=ZIP_DEFLATED) as z:
        for name, content in sorted(files.items()):
            z.writestr("tram-forecast/" + name, content)
        z.writestr("tram-forecast/MANIFEST.sha256", manifest)
    verification = {archive.name: verify_archive(archive, "tram-forecast/", files)}
    outputs = [archive]
    if ml_files:
        ml_archive = destination / "ds-ml-candidate-review.zip"
        with ZipFile(ml_archive, "x", compression=ZIP_DEFLATED) as z:
            for name, content in sorted(ml_files.items()):
                z.writestr("ml-review/" + name, content)
            z.writestr("ml-review/MANIFEST.sha256", "".join(
                f"{hashlib.sha256(content).hexdigest()}  {name}\n"
                for name, content in sorted(ml_files.items())
            ))
        outputs.append(ml_archive)
        verification[ml_archive.name] = verify_archive(ml_archive, "ml-review/", ml_files)
    (destination / "ds-status.md").write_text(
        "# Комплект DS ожидает входные материалы\n\n"
        "Submission не создан: актуальный sample и веса модели не переданы.\n"
        "В GitHub есть ML-код и отчёт 0,8287 до округления; это ещё не финальная QA-приёмка.\n"
        "Нужны аудит ключей Игоря, прогноз Георгия, принятое округление и preflight.\n"
        "Сохраняем полный исходный sample с № 5 и всеми таймстемпами; аудит сообщает 14 640 строк.\n"
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
        "ml_source_commit": args.ml_ref,
        "not_done": ["deployment", "messages", "commit", "push", "actual DS submission",
                     "final owner acceptance", "real-model backtest", "HTTP load test"],
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"Prepared {len(files)} public source/document files in {archive}")
    print("No actual DS submission or private credentials packaged; ML sources, if included, are for review.")


if __name__ == "__main__":
    main()
