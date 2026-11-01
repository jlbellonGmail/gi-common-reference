"""Huella de la CA en la evidencia de gi-dev: SHA-256 del DER del certificado, como en el README.

`tests/fixtures/supabase-prod-ca-2021.crt` es la CA raíz pública de Supabase (`prod-ca-2021.crt`),
la misma que se usa con `--sslrootcert`.
"""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CA = ROOT / "tests" / "fixtures" / "supabase-prod-ca-2021.crt"
README = ROOT / "acceptance" / "locales" / "gi-dev" / "README.md"


def _gi_dev() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gi_dev", ROOT / "tools/acceptance/gi_dev.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gi_dev = _gi_dev()


def _documented_fingerprint() -> str:
    match = re.search(
        r"Huella SHA-256 \(DER\) de la raíz: `([0-9A-F:]+)`", README.read_text("utf-8")
    )
    assert match is not None
    return match.group(1)


def _pem(tmp_path: Path, newline: bytes) -> Path:
    pem = CA.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline)
    path = tmp_path / f"ca-{len(newline)}.crt"
    path.write_bytes(pem)
    return path


def test_fingerprint_does_not_depend_on_line_endings(tmp_path: Path) -> None:
    lf, crlf = _pem(tmp_path, b"\n"), _pem(tmp_path, b"\r\n")
    assert lf.read_bytes() != crlf.read_bytes()
    assert gi_dev.ca_fingerprints(lf) == gi_dev.ca_fingerprints(crlf)


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_fingerprint_matches_the_documented_one(tmp_path: Path, newline: bytes) -> None:
    assert gi_dev.ca_fingerprints(_pem(tmp_path, newline)) == [_documented_fingerprint()]


def test_tls_header_shows_the_der_fingerprint(tmp_path: Path) -> None:
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}", encoding="utf-8")
    env = gi_dev.Env(credentials, "localhost", "", 5432, "verify-full", CA)
    assert env.describe_tls() == (
        f"sslmode=verify-full sslrootcert={CA.name} (SHA-256 DER {_documented_fingerprint()})"
    )


def _invalid_files() -> dict[str, bytes]:
    pem = CA.read_bytes().replace(b"\r\n", b"\n")
    return {
        "texto": b"no es un certificado\n",
        "vacio": b"",
        "base64-corrupto": pem[:100] + b"!" * 40 + pem[140:],
        "truncado": pem[:600],
    }


@pytest.mark.parametrize("content", _invalid_files().values(), ids=_invalid_files().keys())
def test_invalid_file_is_rejected_with_a_clear_message(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "ca.crt"
    path.write_bytes(content)
    with pytest.raises(ValueError, match=r"ca\.crt no contiene un certificado X\.509 PEM válido"):
        gi_dev.ca_fingerprints(path)


def test_cli_rejects_invalid_sslrootcert_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "ca.crt"
    path.write_bytes(b"no es un certificado\n")
    argv = ["gi_dev.py", "--environment", "test", "--credentials", str(tmp_path / "no.json")]
    argv += ["--pooler-host", "localhost", "--sslrootcert", str(path), "probe"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exit_info:
        gi_dev.main()
    assert exit_info.value.code == 2
    assert "--sslrootcert: ca.crt no contiene un certificado X.509 PEM válido" in (
        capsys.readouterr().err
    )
