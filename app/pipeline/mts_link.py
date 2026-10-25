"""Запись МТС Линк -> один MP4: экран + звук всех микрофонов по таймингам.

Логика склейки перенесена из форка github.com/lumiragee/mtslinker (mts_merge.py).
МТС Линк хранит запись кусками: звук лектора, демонстрация экрана, микрофоны и
камеры участников, многие куски идут одновременно. Поэтому:
  - звук = все куски со звуком, каждый на своём месте в записи;
  - картинка = демонстрация экрана, когда её нет — чёрный кадр, камеры не накладываются;
  - учитываются потоки, начатые до старта записи (snapshot + upTime), и вырезанные места (cut.end).

Куски кэшируются в runtime/tmp/mts_link/<id>/ и докачиваются при повторе
той же ссылки; после успешной склейки папка удаляется.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from common import ROOT, Cancelled, check_cancel, sanitize

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
W, H, FPS = 1920, 1080, 5
FALLBACK_MIN_WIDTH = 1000  # если в данных нет пометки screensharing — экраном считаем широкое видео
TITLE_MAX = 80             # длинные названия ломают пути на Windows (MAX_PATH)
CACHE_DIR = ROOT / "runtime" / "tmp" / "mts_link"

# https://my.mts-link.ru/<org>/<room>/record-new/<сессия>[/record-file/<запись>]
# https://hse.mts-link.ru/... и другие поддомены
# https://my.mts-link.ru/j/<org>/<room>/record-new/<сессия>/<токен публичной ссылки>
_URL_RE = re.compile(
    r"^https?://(?P<host>(?:[a-z0-9-]+\.)*mts-link\.ru)/(?:[^/?#]+/)?\d+/\d+/record-new/(?P<event>\d+)"
    r"(?:/record-file/(?P<record>\d+)|/(?P<token>[^/?#]+))?(?:[/?#]|$)",
    re.IGNORECASE,
)
_SESSION_RE = re.compile(r"[A-Za-z0-9._~%+/=-]{1,4096}")
TRIES = 8  # попыток скачать кусок; после обрыва докачка с того же места


class MtsLinkError(RuntimeError):
    """Понятная пользователю ошибка скачивания или склейки."""


class PieceGone(Exception):
    """Кусок насовсем недоступен на сервере (4xx): такой пропускаем."""


@dataclass(frozen=True)
class RecordLink:
    host: str
    event_session: str
    record_id: str | None = None
    token: str | None = None

    @property
    def key(self) -> str:
        """Имя папки кэша кусков."""
        return f"{self.event_session}_{self.record_id}" if self.record_id else self.event_session


def parse_url(url: str) -> RecordLink:
    """Ссылка из адресной строки -> части, нужные для API."""
    m = _URL_RE.match(url.strip().strip("\"'").strip())
    token = m.group("token") if m else None
    if not m or (token and token.lower() == "record-file"):
        raise ValueError("Это не ссылка на запись МТС Линк. Скопируй адрес открытой записи: "
                         "https://my.mts-link.ru/…/record-new/…")
    return RecordLink(m.group("host").lower(), m.group("event"), m.group("record"), token)


def clean_session_id(value: str | None) -> str | None:
    """Значение cookie входа (access или старый sessionId) из поля ввода.

    Допускает «access=…», «sessionId=…» и кавычки. Пустое -> None.
    """
    value = (value or "").strip().strip("\"'").strip()
    if value.lower().startswith(("access=", "sessionid=")):
        value = value.split("=", 1)[1].strip().strip("\"'")
    if not value:
        return None
    if not _SESSION_RE.fullmatch(value):
        raise ValueError("Вход выглядит неправильно: скопируй только значение cookie access (или sessionId)")
    return value


def _auth_cookies(session_id: str | None) -> dict:
    """Раньше вход хранился в cookie sessionId, теперь у МТС Линк cookie access (строка на eyJ…)."""
    if not session_id:
        return {}
    return {"access": session_id} if session_id.startswith("eyJ") else {"sessionId": session_id}


def fetch_record(link: RecordLink, session_id: str | None = None, timeout: float = 60) -> dict:
    """JSON записи: длительность, название и eventLogs со ссылками на куски."""
    import requests

    if link.record_id:
        path = f"/api/event-sessions/{link.event_session}/record-files/{link.record_id}/flow"
        hosts = [link.host, "my.mts-link.ru"]
    else:
        path = f"/api/eventsessions/{link.event_session}/record"
        # публичные ссылки с токеном API отдаёт через gw.mts-link.ru
        hosts = (["gw.mts-link.ru"] if link.token else []) + [link.host, "my.mts-link.ru"]
    params = {"withoutCuts": "false"}
    if link.token:
        params["recordAccessToken"] = link.token
    cookies = _auth_cookies(session_id)

    forbidden, last = False, None
    for host in dict.fromkeys(hosts):
        try:
            # без редиректов: cookie sessionId не должна уехать на чужой хост
            url = f"https://{host}{path}"
            r = requests.get(url, params=params, cookies=cookies, headers={"User-Agent": UA},
                             timeout=timeout, allow_redirects=False, proxies=_proxies(url))
        except requests.RequestException as e:
            last = f"сеть: {e.__class__.__name__}"  # текст исключения содержит URL с токеном
            continue
        if r.status_code in (401, 403):
            forbidden = True
            continue
        if r.status_code != 200:
            last = f"HTTP {r.status_code}"
            continue
        try:
            data = r.json()
        except ValueError:
            last = "ответ не JSON"
            continue
        if not isinstance(data, dict):
            last = "неожиданный формат ответа"
            continue
        error = data.get("error")
        if error and "eventLogs" not in data:
            code = error.get("code") if isinstance(error, dict) else None
            if code in (401, 403):
                forbidden = True
            else:
                last = f"ошибка API {code or ''}".strip()
            continue
        return data
    if forbidden:
        raise MtsLinkError("Доступ к записи запрещён: запись закрытая, а вход не указан или устарел. "
                           "Добавь ссылку заново и вставь свежее значение cookie access (или sessionId) "
                           "с my.mts-link.ru.")
    raise MtsLinkError(f"Не удалось получить данные записи ({last})")


def _proxies(url: str) -> dict:
    """Прокси только из переменных окружения, как у httpx в форке.

    requests на Windows ещё и подхватывает системный прокси из реестра (его ставят
    VPN-клиенты): записи МТС Линк качаем напрямую, как и форк.
    """
    import urllib.request

    host = urlsplit(url).hostname or ""
    env = {} if urllib.request.proxy_bypass_environment(host) else urllib.request.getproxies_environment()
    return {"http": env.get("http"), "https": env.get("https")}


def _piece_name(url: str) -> str:
    """Имя файла куска: стабильно между запусками и без коллизий одинаковых basename."""
    bare = url.split("?", 1)[0]
    base = re.sub(r"[^\w.-]+", "_", Path(urlsplit(bare).path).name)[-60:].strip("._") or "piece"
    return f"{hashlib.sha1(bare.encode('utf-8')).hexdigest()[:10]}_{base}"


def _download(url: str, directory: Path, label: str, log: logging.Logger, retries: int = TRIES) -> Path:
    """Скачивает кусок с таймаутами и повторами; после обрыва докачивает с того же места.

    Уже скачанный файл не трогает. 4xx -> PieceGone (кусок удалён на сервере).
    """
    import requests

    path = directory / _piece_name(url)
    if path.exists() and path.stat().st_size > 0:
        return path
    part = path.with_name(path.name + ".part")
    for attempt in range(1, retries + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": UA}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            # минута тишины от сервера = обрыв, а не вечное ожидание
            with requests.get(url, headers=headers, stream=True, timeout=(30, 60), proxies=_proxies(url)) as r:
                if have and r.status_code == 416:  # в .part уже весь файл
                    break
                if 400 <= r.status_code < 500:
                    raise PieceGone(f"сервер ответил {r.status_code}")
                r.raise_for_status()
                append = bool(have) and r.status_code == 206  # докачку не умеет — качаем заново
                done = have if append else 0
                size = int(r.headers.get("content-length") or 0)
                total = 0 if r.headers.get("content-encoding") else size + done
                next_pct = (done * 100 // total // 20 + 1) * 20 if total else 101
                with part.open("ab" if append else "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        check_cancel()  # недокачанный .part останется: докачается при повторном запуске
                        f.write(chunk)
                        done += len(chunk)
                        if total and done * 100 >= next_pct * total and next_pct < 100:
                            log.info("Скачивание файла %s: %d%%", label, next_pct)
                            next_pct += 20
                if total and done < total:
                    raise requests.ConnectionError(f"обрыв на {done} из {total} байт")
            break
        except PieceGone:
            raise
        except (requests.RequestException, OSError) as e:
            if attempt == retries:
                raise
            log.warning("Файл %s: обрыв (%s), попытка %d/%d", label, e.__class__.__name__, attempt + 1, retries)
            time.sleep(min(60, 5 * attempt))
    part.replace(path)
    return path


def _probe(path: Path) -> tuple[int, bool, float] | None:
    """(ширина видео или 0, есть ли звук, длительность); None если файл битый."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        data = json.loads(r.stdout or "{}")
    except FileNotFoundError as e:
        raise MtsLinkError("Не найден ffprobe: установи FFmpeg и добавь его в PATH") from e
    except (OSError, ValueError):
        return None
    streams = data.get("streams") or []
    if not streams:
        return None
    width = max((int(s.get("width") or 0) for s in streams if s.get("codec_type") == "video"), default=0)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return width, has_audio, duration


class Piece:
    """Кусок файла, стоящий на своём месте в записи."""

    def __init__(self, pid, fidx, path, start, offset, length, kind, width, has_audio):
        self.pid, self.fidx, self.path = pid, fidx, path
        self.start, self.offset, self.length = start, offset, length
        self.kind, self.width, self.has_audio = kind, width, has_audio

    @property
    def end(self) -> float:
        return self.start + self.length


def stream_kind(stream) -> str | None:
    if isinstance(stream, dict):
        if "screensharing" in stream:
            return "screen"
        if "conference" in stream:
            return "camera"
    return None


def collect_items(record: dict) -> tuple[list[tuple], list[float]]:
    """Все упоминания файлов: [(время в записи, позиция в файле, url, тип)] и времена cut.end.

    Потоки, начатые до начала записи или до конца вырезанного куска, лежат не в
    mediasession.add, а в снимке состояния (snapshot) с upTime — сколько секунд
    поток уже шёл к этому моменту.
    """
    items, cuts = {}, []
    for ev in record.get("eventLogs", []):
        if not isinstance(ev, dict):
            continue
        rel = float(ev.get("relativeTime") or 0)
        if ev.get("module") == "cut.end":
            cuts.append(rel)
        data = ev.get("data")
        if isinstance(data, dict) and data.get("url"):
            items.setdefault((data["url"], round(rel, 3)),
                             (rel, 0.0, data["url"], stream_kind(data.get("stream"))))
        snap = ev.get("snapshot")
        if isinstance(snap, dict) and isinstance(snap.get("data"), dict):
            for m in snap["data"].get("mediasession") or []:
                if isinstance(m, dict) and m.get("url"):
                    items[(m["url"], round(rel, 3))] = (rel, float(m.get("upTime") or 0), m["url"],
                                                        stream_kind(m.get("stream")))
    return sorted(items.values()), sorted(cuts)


def make_pieces(items, cuts, duration, info) -> list[Piece]:
    """info: url -> (fidx, path, width, has_audio, dur).

    Кусок длится до конца файла, до следующего появления того же файла или до
    следующего вырезанного места — что раньше.
    """
    by_url: dict[str, list] = {}
    for rel, off, url, kind in items:
        if url in info:
            by_url.setdefault(url, []).append((rel, off, kind))
    pieces = []
    for url, lst in by_url.items():
        fidx, path, width, has_audio, fdur = info[url]
        lst.sort()
        for i, (rel, off, kind) in enumerate(lst):
            end = min(duration, rel + max(fdur - off, 0))
            if i + 1 < len(lst):
                end = min(end, lst[i + 1][0])
            nxt = [c for c in cuts if c > rel + 1e-3]
            if nxt:
                end = min(end, nxt[0])
            if end - rel > 0.05:
                pieces.append(Piece(len(pieces), fidx, path, rel, off, end - rel, kind, width, has_audio))
    return pieces


def build_timeline(duration, screens) -> list[tuple]:
    """Делит запись на отрезки (a, b, 'экран'|'чёрный', кусок).

    Если экранов несколько сразу — берём тот, что включили позже.
    """
    pts = {0.0, duration}
    for sc in screens:
        pts.update((max(0.0, sc.start), min(duration, sc.end)))
    pts = sorted(p for p in pts if 0 <= p <= duration)
    out = []
    for a, b in zip(pts, pts[1:]):
        if b - a < 0.05:
            continue
        mid = (a + b) / 2
        cover = [sc for sc in screens if sc.start <= mid < sc.end]
        item = ("экран", max(cover, key=lambda sc: sc.start)) if cover else ("чёрный", None)
        if out and out[-1][2:] == item and abs(out[-1][1] - a) < 1e-6:
            out[-1] = (out[-1][0], b) + item
        else:
            out.append((a, b) + item)
    return out


@dataclass
class MergePlan:
    duration: float
    inputs: list[list[str]] = field(default_factory=list)  # аргументы ffmpeg на каждый вход
    filters: list[str] = field(default_factory=list)       # строки filter_complex
    screens: int = 0
    audios: int = 0
    screen_seconds: float = 0.0
    black_seconds: float = 0.0


def plan_merge(record: dict, info: dict, items=None, cuts=None) -> MergePlan:
    """Входы и filter_complex для ffmpeg. Пути входов — имена файлов (ffmpeg запускается в папке кусков)."""
    duration = float(record.get("duration") or 0)
    if not duration:
        raise MtsLinkError("В данных записи нет длительности")
    if items is None:
        items, cuts = collect_items(record)
    marked = any(kind for *_, kind in items)

    pieces = make_pieces(items, cuts or [], duration, info)
    screens, audios = [], []
    for pc in pieces:
        is_screen = (pc.kind == "screen") if marked else (pc.width >= FALLBACK_MIN_WIDTH)
        if pc.width and is_screen:
            screens.append(pc)
        if pc.has_audio:
            audios.append(pc)
    if not audios:
        raise MtsLinkError("В записи не нашлось звука")

    plan = MergePlan(duration, screens=len(screens), audios=len(audios))
    timeline = build_timeline(duration, screens)
    plan.screen_seconds = sum(b - a for a, b, kind, _ in timeline if kind == "экран")
    plan.black_seconds = sum(b - a for a, b, kind, _ in timeline if kind == "чёрный")

    def add_input(path, offset, length, video=False) -> int:
        # каждый кусок читается со своего места в файле, ничего не копится в памяти;
        # у видео размер кадра может меняться посреди записи — не пересобираем фильтры
        opts = ["-reinit_filter", "0"] if video else []
        if offset > 0.001:
            opts += ["-ss", f"{offset:.3f}"]
        plan.inputs.append(opts + ["-t", f"{length + (1 if video else 0):.3f}", "-i", Path(path).name])
        return len(plan.inputs) - 1

    fl = plan.filters
    alabels = []
    for n, pc in enumerate(audios):  # звук: каждый кусок со своей задержкой
        i = add_input(pc.path, pc.offset, pc.length)
        ms = int(pc.start * 1000)
        fl.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                  f"adelay={ms}|{ms}[a{n}]")
        alabels.append(f"[a{n}]")

    vlabels = []
    for k, (a, b, kind, pc) in enumerate(timeline):  # картинка: отрезки по очереди
        length = b - a
        if kind == "чёрный":
            fl.append(f"color=c=black:s={W}x{H}:r={FPS}:d={length:.3f},setsar=1,format=yuv420p[v{k}]")
        else:
            i = add_input(pc.path, pc.offset + a - pc.start, length, video=True)
            fl.append(f"[{i}:v]setpts=PTS-STARTPTS,fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                      f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,"
                      f"tpad=stop=-1:stop_mode=add:color=black,trim=duration={length:.3f},"
                      f"setpts=PTS-STARTPTS[v{k}]")
        vlabels.append(f"[v{k}]")
    if len(vlabels) == 1:
        fl.append(f"{vlabels[0]}fps={FPS}[vout]")
    else:
        fl.append(f"{''.join(vlabels)}concat=n={len(vlabels)}:v=1:a=0,fps={FPS}[vout]")

    if len(alabels) == 1:
        fl.append(f"{alabels[0]}apad,atrim=0:{duration}[aout]")
    else:
        fl.append(f"{''.join(alabels)}amix=inputs={len(alabels)}:normalize=0:dropout_transition=0,"
                  f"apad,atrim=0:{duration}[aout]")
    return plan


_FFMPEG_MAJOR: list[int | None] = []


def _ffmpeg_major() -> int | None:
    if not _FFMPEG_MAJOR:
        try:
            out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace").stdout
        except OSError:
            out = ""
        m = re.match(r"ffmpeg version n?(\d+)\.", out)
        _FFMPEG_MAJOR.append(int(m.group(1)) if m else None)  # git-сборки — свежие
    return _FFMPEG_MAJOR[0]


def _filter_script_args(script: str) -> list[str]:
    """ffmpeg 7+ читает filter_complex из файла через -/filter_complex,
    -filter_complex_script там устарел; в 4–6 есть только он."""
    major = _ffmpeg_major()
    if major is not None and major < 7:
        return ["-filter_complex_script", script]
    return ["-/filter_complex", script]


def _run_ffmpeg(plan: MergePlan, directory: Path, output: Path, log: logging.Logger) -> None:
    script = directory / "filter.txt"
    script.write_text(";\n".join(plan.filters), encoding="utf-8")
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-nostats",
            "-progress", "pipe:1", "-y"]
    for spec in plan.inputs:
        args += spec
    args += _filter_script_args(script.name)
    args += ["-map", "[vout]", "-map", "[aout]", "-r", str(FPS),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-tune", "stillimage",
             "-c:a", "aac", "-b:a", "128k", "-t", str(plan.duration),
             "-movflags", "+faststart", "-f", "mp4", str(output)]
    with tempfile.TemporaryFile() as err:
        # cwd = папка кусков: входы по коротким именам, командная строка Windows не переполнится
        proc = subprocess.Popen(args, cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=err, text=True, encoding="utf-8", errors="replace")
        next_pct = 10
        try:
            for line in proc.stdout:
                check_cancel()
                key, _, value = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and value.isdigit():  # out_time_ms тоже в мкс
                    pct = int(value) / 1e6 / plan.duration * 100
                    # последний кадр кончается на долю секунды раньше длительности: 99% = всё закодировано
                    if pct >= 99 and next_pct <= 100:
                        # дальше ffmpeg переписывает файл целиком ради +faststart, прогресса в это
                        # время нет; без этой строки казалось, что сборка зависла на 90%
                        log.info("Сборка MP4: %d%%, дописываю файл...", 100)
                        next_pct = 110
                    elif pct >= next_pct:
                        # отчёт приходит раз в полсекунды: на быстром ПК между ними бывает больше 10%
                        log.info("Сборка MP4: %d%%", int(pct) // 10 * 10)
                        next_pct = (int(pct) // 10 + 1) * 10
                elif key == "progress" and value == "end" and next_pct <= 100:
                    log.info("Сборка MP4: %d%%", 100)  # ffmpeg закончил раньше, чем мы увидели 99%
                    next_pct = 110
            check_cancel()
        except Cancelled:
            proc.kill()
            proc.wait()
            raise
        code = proc.wait()
        if code:
            err.seek(0)
            tail = err.read().decode("utf-8", "replace").strip().splitlines()[-5:]
            raise MtsLinkError(f"ffmpeg не смог склеить запись (код {code}): {' | '.join(tail)[:500]}")


def build(directory: Path, record: dict, output: Path, log: logging.Logger,
          download: Callable = _download) -> Path:
    """Скачивает куски в directory и склеивает их в output (MP4)."""
    if not float(record.get("duration") or 0):
        raise MtsLinkError("В данных записи нет длительности")
    items, cuts = collect_items(record)
    urls = list(dict.fromkeys(url for _, _, url, _ in items))
    if not urls:
        raise MtsLinkError("В записи не нашлось ни одного видео/аудио куска")
    log.info("Файлов в записи: %d, длительность: %.0f мин", len(urls), float(record["duration"]) / 60)

    info = {}
    for i, url in enumerate(urls, 1):
        check_cancel()
        label = f"{i}/{len(urls)}"
        log.info("Скачивание файла %s...", label)
        try:
            path = download(url, directory, label, log)
        except Cancelled:
            raise
        except PieceGone as e:
            log.warning("Файл %s недоступен на сервере, пропускаю: %s", label, e)
            continue
        except Exception as e:  # noqa: BLE001
            # раньше такой кусок молча пропускался, и из записи выпадали полчаса звука
            raise MtsLinkError(
                f"Файл {label} не скачался даже после {TRIES} попыток ({e.__class__.__name__}). "
                "Добавь ссылку ещё раз: скачанное не пропадёт, докачается с того же места") from e
        probed = _probe(path)
        if probed is None:
            log.warning("Файл %s битый, пропускаю", label)
            continue
        width, has_audio, fdur = probed
        info[url] = (len(info), path, width, has_audio, fdur)

    plan = plan_merge(record, info, items, cuts)
    log.info("Трансляций экрана: %d, звуковых дорожек: %d; картинка: экран %.0f мин, чёрный %.0f мин",
             plan.screens, plan.audios, plan.screen_seconds / 60, plan.black_seconds / 60)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".partial.mp4")
    log.info("Сборка MP4: экран + %d звуковых дорожек (несколько минут)...", plan.audios)
    try:
        _run_ffmpeg(plan, directory, partial, log)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
    return output


def _title(record: dict, link: RecordLink) -> str:
    raw = re.sub(r"[\x00-\x1f]", " ", str(record.get("name") or ""))
    title = sanitize(raw).strip(" .")[:TITLE_MAX].strip(" .")
    return title or f"Запись МТС Линк {link.event_session}"


def download_recording(url: str, dest_dir: Path, session_id: str | None = None,
                       log: logging.Logger | None = None,
                       on_title: Callable[[str], None] | None = None,
                       cache_root: Path | None = None) -> Path:
    """Скачивает запись по ссылке и склеивает в dest_dir/<название>.mp4."""
    log = log or logging.getLogger("videonotes")
    link = parse_url(url)
    log.info("Скачивание записи МТС Линк: сессия %s%s", link.event_session,
             f", файл записи {link.record_id}" if link.record_id else "")
    record = fetch_record(link, session_id)
    title = _title(record, link)
    log.info("Запись: %s", title)
    if on_title:
        on_title(title)

    cache = (cache_root or CACHE_DIR) / link.key
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "record.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    dest_dir.mkdir(parents=True, exist_ok=True)
    output = build(cache, record, dest_dir / f"{title}.mp4", log)
    shutil.rmtree(cache, ignore_errors=True)  # куски бывают по гигабайту, MP4 уже собран
    log.info("MP4 записи собран: %s (%.1f МБ)", output.name, output.stat().st_size / 1e6)
    return output
