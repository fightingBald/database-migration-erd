"""The published package must work outside the repository without bundled data."""

import email
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from erd_generator import __version__

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def distribution(tmp_path_factory):
    folder = tmp_path_factory.mktemp("distribution")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(folder)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = list(folder.glob("migration_erd-*.whl"))
    assert len(wheels) == 1
    return wheels[0], next(folder.glob("*.tar.gz"))


def test_distributions_include_runtime_and_exclude_local_data(distribution):
    wheel, sdist = distribution
    with zipfile.ZipFile(wheel) as archive:
        paths = archive.namelist()
        metadata = email.message_from_bytes(
            archive.read(next(p for p in paths if p.endswith("/METADATA")))
        )
        assert metadata["Name"] == "migration-erd"
        assert metadata["Version"] == __version__
        assert metadata["Requires-Python"] == ">=3.11"
        urls = dict(value.split(", ", 1) for value in metadata.get_all("Project-URL"))
        assert (
            urls["Homepage"] == "https://fightingbald.github.io/database-migration-erd/"
        )
        assert (
            urls["Source"] == "https://github.com/fightingBald/database-migration-erd"
        )
        assert set(metadata.get_all("Requires-Dist")) == set(
            (ROOT / "requirements.txt").read_text().splitlines()
        )
        assert "erd_generator/cli.py" in paths
        assert all(p.startswith("erd_generator/") or ".dist-info/" in p for p in paths)
    with tarfile.open(sdist) as archive:
        paths += [
            str(Path(p).relative_to(archive.getnames()[0])) for p in archive.getnames()
        ]
    forbidden = {"tests", "generated", "site", "docs", "scripts", ".github", ".venv"}
    assert not any(forbidden.intersection(Path(p).parts) for p in paths)
    assert not any(Path(p).suffix in {".sql", ".svg", ".png", ".pyc"} for p in paths)


def test_installed_command_works_outside_checkout(distribution, tmp_path):
    wheel, _ = distribution
    target = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-compile",
            "--target",
            str(target),
            str(wheel),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    env = {**os.environ, "PYTHONPATH": str(target)}
    command = target / "bin" / "migration-erd"

    def run(*args):
        return subprocess.run(
            [str(command), *map(str, args)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    version = run("--version")
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == f"migration-erd {__version__}"
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001.sql").write_text("CREATE TABLE books(id int PRIMARY KEY);")
    output = tmp_path / "schema.d2"
    result = run(migrations, output)
    assert result.returncode == 0, result.stderr
    source = output.read_text()
    assert '"books"' in source and "shape: sql_table" in source
    assert not output.with_suffix(".svg").exists()
    assert not (tmp_path / "parse_log").exists()
    (migrations / "002.sql").write_text("CREATE INDEX broken ON missing(id);")
    result = run(migrations, output)
    assert result.returncode == 1
    assert output.read_text() == source
    assert "INCOMPLETE" in output.with_suffix(".partial.d2").read_text()
