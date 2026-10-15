"""Статические проверки .bat для Windows: их нельзя прогнать в CI, поэтому ловим типовые ловушки cmd."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BAT_DIR = ROOT / "scripts" / "windows"
BATS = sorted(BAT_DIR.glob("*.bat"))


def _unescaped(line: str, chars: str) -> list[int]:
    """Позиции символов из chars вне кавычек и без ^ перед ними."""
    found, quoted, i = [], False, 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == "^":
            i += 2
            continue
        elif not quoted and ch in chars:
            found.append(i)
        i += 1
    return found


def paren_problems(text: str) -> list[tuple[int, str]]:
    """Строки echo со скобками внутри многострочного блока (...).

    cmd закрывает блок на первой неэкранированной ')' вне кавычек, даже посреди текста echo:
    остаток строки становится синтаксической ошибкой, а команды после неё выполняются
    уже вне if. Поэтому внутри блоков скобки в echo пишем как ^( и ^).
    """
    problems, depth = [], 0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().lstrip("@").strip()
        low = line.lower()
        if not line or low == "rem" or low.startswith(("rem ", "::", ":")):
            continue
        if depth and line.startswith(")"):
            depth -= 1
            line = line[1:].strip()
            if line.lower().startswith("else"):
                line = line[4:].strip()
        if depth and re.match(r"(?i)echo([\s.:]|$)", line) and _unescaped(line, "()"):
            problems.append((n, raw.strip()))
        opens = _unescaped(line, "(")
        if opens and opens[-1] == len(line) - 1:
            depth += 1
    return problems


def test_bat_files_found():
    names = {p.name for p in BATS}
    assert {"setup.bat", "process.bat", "watch.bat", "web.bat", "transcribe.bat"} <= names


def test_linter_catches_unescaped_parens_in_block():
    bad = (
        "if not exist venv\\Scripts\\python.exe (\r\n"
        "  echo Сначала запусти setup.bat (установка зависимостей)\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
    )
    assert paren_problems(bad) == [(2, "echo Сначала запусти setup.bat (установка зависимостей)")]
    fixed = bad.replace("(установка зависимостей)", "^(установка зависимостей^)")
    assert paren_problems(fixed) == []
    # вне блока и внутри кавычек скобки безопасны
    assert paren_problems('echo [2/5] Зависимости (torch)\r\nif x (\r\n  echo "a (b)"\r\n)\r\n') == []
    # ветка else тоже блок
    assert paren_problems("if x (\r\n  echo a\r\n) else (\r\n  echo b (c)\r\n)\r\n") == [(4, "echo b (c)")]


@pytest.mark.parametrize("bat", BATS, ids=lambda p: p.name)
def test_no_unescaped_parens_in_blocks(bat):
    assert paren_problems(bat.read_bytes().decode("utf-8")) == []


@pytest.mark.parametrize("bat", BATS, ids=lambda p: p.name)
def test_utf8_without_bom_and_chcp_before_cyrillic(bat):
    raw = bat.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM ломает первую строку (@echo off)"
    lines = raw.decode("utf-8").splitlines()
    first_non_ascii = next((i for i, l in enumerate(lines) if not l.isascii()), None)
    if first_non_ascii is not None:
        chcp = next((i for i, l in enumerate(lines) if l.strip().lower().startswith("chcp 65001")), None)
        assert chcp is not None and chcp < first_non_ascii, "chcp 65001 должен стоять до первой кириллицы"


def test_bat_files_pinned_to_crlf():
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert re.search(r"^\*\.bat\s+.*eol=crlf", attrs, re.M)


def test_cli_commands_used_by_bats_exist():
    main_src = (ROOT / "app" / "pipeline" / "main.py").read_text(encoding="utf-8")
    used = set()
    for bat in BATS:
        used |= set(re.findall(r"main\.py\s+([a-z][\w-]*)", bat.read_bytes().decode("utf-8")))
    assert {"process", "watch", "transcribe"} <= used
    for cmd in used:
        assert f'cmd == "{cmd}"' in main_src, f"main.py не знает команду {cmd}"


def test_web_bat_listens_locally():
    text = (BAT_DIR / "web.bat").read_bytes().decode("utf-8")
    assert 'set "VIDEONOTES_HOST=127.0.0.1"' in text
    assert "app\\web.py %PORT%" in text


def test_server_host_from_env(monkeypatch):
    import web

    monkeypatch.delenv("VIDEONOTES_HOST", raising=False)
    assert web._server_host() == "0.0.0.0"  # Docker и прежнее поведение
    monkeypatch.setenv("VIDEONOTES_HOST", " 127.0.0.1 ")
    assert web._server_host() == "127.0.0.1"
    monkeypatch.setenv("VIDEONOTES_HOST", "")
    assert web._server_host() == "0.0.0.0"
