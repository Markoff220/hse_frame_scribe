import http.server
import logging
import shutil
import subprocess
import threading

import numpy as np
import pytest

import web  # noqa: F401 — добавляет app/pipeline в sys.path
import common
import mts_link as M

LOG = logging.getLogger("test.mts")
HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# --- ссылки -----------------------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://my.mts-link.ru/146049682/24264533545/record-new/23673458754/record-file/2104961441",
     ("my.mts-link.ru", "23673458754", "2104961441", None)),
    ("https://my.mts-link.ru/12345678/987654321/record-new/123456789",
     ("my.mts-link.ru", "123456789", None, None)),
    ("  https://HSE.mts-link.ru/1/2/record-new/3/record-file/4?utm=x#t ",
     ("hse.mts-link.ru", "3", "4", None)),
    ('"https://my.mts-link.ru/1/2/record-new/3/"', ("my.mts-link.ru", "3", None, None)),
    ("https://my.mts-link.ru/j/1/2/record-new/123456/token-value?ignored=true",
     ("my.mts-link.ru", "123456", None, "token-value")),
])
def test_parse_url(url, expected):
    link = M.parse_url(url)
    assert (link.host, link.event_session, link.record_id, link.token) == expected


@pytest.mark.parametrize("url", [
    "https://example.com/1/2/record-new/3",
    "https://my.mts-link.ru.evil.com/1/2/record-new/3",
    "https://my.mts-link.ru@evil.com/1/2/record-new/3",
    "https://my.mts-link.ru/1/2/record-new/3abc",
    "https://my.mts-link.ru/1/2/record-new/3/record-file",
    "https://my.mts-link.ru/1/2/webinar/3",
    "",
])
def test_parse_url_rejects_other_links(url):
    with pytest.raises(ValueError):
        M.parse_url(url)


def test_clean_session_id():
    assert M.clean_session_id("  abc123def ") == "abc123def"
    assert M.clean_session_id('sessionId="abc123"') == "abc123"
    jwt = "eyJhbGciOiJIUzI1NiJ9." + "x" * 600 + ".sig_-"  # cookie access длиннее 512 символов
    assert M.clean_session_id(f"access={jwt}") == jwt
    assert M.clean_session_id("") is None and M.clean_session_id(None) is None
    for bad in ("abc def", "abc;x=1", "abc\r\nX: y"):
        with pytest.raises(ValueError):
            M.clean_session_id(bad)


# --- раскладка кусков -------------------------------------------------------

def _rec(duration, *events):
    return {"name": "Лекция", "duration": duration, "eventLogs": list(events)}


def _add(rel, url, kind):
    stream = {"screensharing": {}} if kind == "screen" else {"conference": {"id": url}}
    return {"module": "mediasession.add", "relativeTime": rel, "data": {"url": url, "stream": stream}}


def _snap(rel, *sessions):
    return {"module": "snapshot", "relativeTime": rel, "snapshot": {"data": {"mediasession": [
        {"url": url, "upTime": up, "stream": {"screensharing": {}} if kind == "screen" else {"conference": {}}}
        for url, up, kind in sessions]}}}


def test_collect_items_reads_snapshots_and_cuts():
    record = _rec(60, _snap(0, ("mic", 5, "camera")), _add(10, "scr", "screen"),
                  {"module": "cut.end", "relativeTime": 20}, _snap(20, ("mic", 25, "camera")), "мусор")
    items, cuts = M.collect_items(record)
    assert items == [(0.0, 5.0, "mic", "camera"), (10.0, 0.0, "scr", "screen"), (20.0, 25.0, "mic", "camera")]
    assert cuts == [20.0]


def test_make_pieces_ends_at_file_end_next_appearance_and_cut():
    items = [(0.0, 5.0, "mic", "camera"), (10.0, 0.0, "scr", "screen"), (20.0, 25.0, "mic", "camera")]
    info = {"mic": (0, "mic.mp4", 0, True, 40.0), "scr": (1, "scr.mp4", 1280, False, 100.0)}
    pieces = M.make_pieces(items, [20.0], 60.0, info)
    spans = sorted((p.path, p.start, p.offset, p.end) for p in pieces)
    assert spans == [
        ("mic.mp4", 0.0, 5.0, 20.0),    # до следующего появления (и cut)
        ("mic.mp4", 20.0, 25.0, 35.0),  # 40 - 25 = 15 с файла осталось
        ("scr.mp4", 10.0, 0.0, 20.0),   # обрезан вырезанным местом
    ]


def test_build_timeline_prefers_latest_screen_and_fills_black():
    a = M.Piece(0, 0, "a", 5, 0, 20, "screen", 1280, False)   # 5..25
    b = M.Piece(1, 1, "b", 10, 0, 5, "screen", 1280, False)   # 10..15 поверх a
    timeline = [(x, y, kind, pc.path if pc else None) for x, y, kind, pc in M.build_timeline(30, [a, b])]
    assert timeline == [(0, 5, "чёрный", None), (5, 10, "экран", "a"), (10, 15, "экран", "b"),
                        (15, 25, "экран", "a"), (25, 30, "чёрный", None)]


def test_plan_merge_requires_audio_and_duration():
    with pytest.raises(M.MtsLinkError, match="длительности"):
        M.plan_merge({"eventLogs": []}, {})
    record = _rec(30, _add(0, "scr", "screen"))
    with pytest.raises(M.MtsLinkError, match="звука"):
        M.plan_merge(record, {"scr": (0, "scr.mp4", 1920, False, 30.0)})


def test_plan_merge_uses_wide_video_as_screen_when_unmarked():
    record = _rec(30, {"relativeTime": 0, "data": {"url": "wide"}}, {"relativeTime": 0, "data": {"url": "cam"}})
    info = {"wide": (0, "/x/wide.mp4", 1920, True, 30.0), "cam": (1, "/x/cam.mp4", 640, True, 30.0)}
    plan = M.plan_merge(record, info)
    assert plan.screens == 1 and plan.audios == 2 and plan.black_seconds == 0
    assert all("/" not in spec[-1] for spec in plan.inputs)  # ffmpeg получает только имена файлов


# --- API МТС Линк -----------------------------------------------------------

class _Resp:
    def __init__(self, status, data=None, text=False):
        self.status_code, self._data, self._text = status, data, text

    def json(self):
        if self._text:
            raise ValueError("not json")
        return self._data


def _fake_get(monkeypatch, answers):
    calls = []

    def get(url, **kw):
        calls.append((url, kw))
        answer = answers[len(calls) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr("requests.get", get)
    return calls


def test_fetch_record_flow_falls_back_to_my_host(monkeypatch):
    link = M.parse_url("https://hse.mts-link.ru/1/2/record-new/3/record-file/4")
    calls = _fake_get(monkeypatch, [_Resp(403), _Resp(200, {"duration": 1, "eventLogs": []})])
    assert M.fetch_record(link, "sid")["duration"] == 1
    assert [c[0] for c in calls] == ["https://hse.mts-link.ru/api/event-sessions/3/record-files/4/flow",
                                     "https://my.mts-link.ru/api/event-sessions/3/record-files/4/flow"]
    assert all(kw["cookies"] == {"sessionId": "sid"} and kw["allow_redirects"] is False for _, kw in calls)


def test_fetch_record_sends_new_access_cookie(monkeypatch):
    link = M.parse_url("https://my.mts-link.ru/1/2/record-new/3/record-file/4")
    calls = _fake_get(monkeypatch, [_Resp(200, {"duration": 1, "eventLogs": []})])
    M.fetch_record(link, "eyJabc.def.ghi")
    assert calls[0][1]["cookies"] == {"access": "eyJabc.def.ghi"}
    assert calls[0][1]["params"] == {"withoutCuts": "false"}


def test_fetch_record_public_token_goes_to_gateway(monkeypatch):
    link = M.parse_url("https://my.mts-link.ru/j/1/2/record-new/123/tok")
    calls = _fake_get(monkeypatch, [_Resp(200, {"duration": 1, "eventLogs": []})])
    M.fetch_record(link)
    url, kw = calls[0]
    assert url == "https://gw.mts-link.ru/api/eventsessions/123/record"
    assert kw["params"] == {"withoutCuts": "false", "recordAccessToken": "tok"} and kw["cookies"] == {}


def test_fetch_record_reports_forbidden_even_if_last_host_fails_otherwise(monkeypatch):
    import requests
    link = M.parse_url("https://hse.mts-link.ru/1/2/record-new/3")
    _fake_get(monkeypatch, [_Resp(200, {"error": {"code": 403}}), requests.ConnectionError("https://x?token=SECRET")])
    with pytest.raises(M.MtsLinkError, match="Доступ к записи запрещён"):
        M.fetch_record(link)


def test_fetch_record_error_does_not_leak_url(monkeypatch):
    import requests
    link = M.parse_url("https://my.mts-link.ru/j/1/2/record-new/3/SECRET")
    calls = _fake_get(monkeypatch, [requests.ConnectionError("https://gw?recordAccessToken=SECRET"), _Resp(200, text=True)])
    with pytest.raises(M.MtsLinkError) as e:
        M.fetch_record(link)
    assert len(calls) == 2  # gw.mts-link.ru и my.mts-link.ru
    assert "SECRET" not in str(e.value) and "не JSON" in str(e.value)


# --- докачка -----------------------------------------------------------------

def test_download_resumes_after_dropped_connection(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 4000  # ~1 МБ
    seen_ranges = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = self.headers.get("Range")
            seen_ranges.append(rng)
            if rng:
                start = int(rng.split("=")[1].rstrip("-"))
                self.send_response(206)
                self.send_header("Content-Length", str(len(payload) - start))
                self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
                self.end_headers()
                self.wfile.write(payload[start:])
            else:  # первый раз рвём соединение на середине
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload[:300_000])
                self.wfile.flush()
                self.close_connection = True

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    try:
        url = f"http://127.0.0.1:{server.server_port}/api-storage/files/abc.mp4?sig=1"
        path = M._download(url, tmp_path, "1/1", LOG)
        assert path.read_bytes() == payload
        # докачка с того места, где оборвалось (неполный последний блок не записывается)
        assert seen_ranges[0] is None and seen_ranges[1].startswith("bytes=")
        assert 0 < int(seen_ranges[1][6:-1]) <= 300_000
        assert not list(tmp_path.glob("*.part"))
        assert M._download(url, tmp_path, "1/1", LOG) == path and len(seen_ranges) == 2  # кэш
    finally:
        server.shutdown()


def test_proxies_come_only_from_environment(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    import urllib.request
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"https": "http://registry:1"})  # системный прокси
    assert M._proxies("https://my.mts-link.ru/api") == {"http": None, "https": None}
    monkeypatch.setenv("HTTPS_PROXY", "http://env:2")
    monkeypatch.setenv("NO_PROXY", "localhost")
    assert M._proxies("https://my.mts-link.ru/api")["https"] == "http://env:2"
    assert M._proxies("https://localhost/x") == {"http": None, "https": None}


def test_piece_names_do_not_collide():
    a = M._piece_name("https://s.webinar.ru/a/video.mp4?x=1")
    b = M._piece_name("https://s.webinar.ru/b/video.mp4")
    assert a != b and a.endswith("_video.mp4") and a == M._piece_name("https://s.webinar.ru/a/video.mp4?x=2")


# --- сквозная склейка на синтетической записи --------------------------------

def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    """Куски в формате МТС: экран (2 с красный, потом синий), микрофон (5 с 300 Гц, потом 440 Гц),
    второй микрофон 880 Гц, зелёная камера и битая ссылка."""
    if not HAS_FFMPEG:
        pytest.skip("нужны ffmpeg и ffprobe")
    src = tmp_path_factory.mktemp("mts_src")
    _ff("-f", "lavfi", "-i", "color=red:s=1280x720:d=2:r=10", "-f", "lavfi", "-i", "color=blue:s=1280x720:d=13:r=10",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-c:v", "libx264", str(src / "screen.mp4"))
    _ff("-f", "lavfi", "-i", "sine=f=300:d=5", "-f", "lavfi", "-i", "sine=f=440:d=15",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]", "-map", "[a]", "-c:a", "aac", str(src / "mic1.mp4"))
    _ff("-f", "lavfi", "-i", "sine=f=880:d=10", "-c:a", "aac", str(src / "mic2.mp4"))
    _ff("-f", "lavfi", "-i", "color=green:s=320x240:d=30:r=10", "-c:v", "libx264", str(src / "camera.mp4"))
    base = "https://events-storage.webinar.ru/api-storage/files/"
    record = _rec(
        30,
        _snap(0, (base + "mic1.mp4", 5, "camera"), (base + "camera.mp4", 0, "camera")),
        _add(10, base + "screen.mp4", "screen"),
        {"module": "cut.end", "relativeTime": 12},
        _snap(12, (base + "screen.mp4", 2, "screen"), (base + "mic1.mp4", 17, "camera"), (base + "camera.mp4", 12, "camera")),
        _add(18, base + "mic2.mp4", "camera"),
        _add(19, base + "broken.mp4", "camera"),
    )

    def fake_download(url, directory, label, log):
        name = url.rsplit("/", 1)[1]
        if name == "broken.mp4":
            raise M.PieceGone("сервер ответил 404")
        dest = directory / M._piece_name(url)
        shutil.copy(src / name, dest)
        return dest
    return record, fake_download


def _pcm(path, start, end, rate=8000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(end - start), "-i", str(path),
                          "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _tone(path, start, end):
    """(громкость RMS, частота пика в Гц) на отрезке."""
    pcm = _pcm(path, start, end)
    rms = float(np.sqrt(np.mean(pcm ** 2))) if len(pcm) else 0.0
    peak = float(np.argmax(np.abs(np.fft.rfft(pcm))) * 8000 / len(pcm)) if len(pcm) else 0.0
    return rms, peak


def _rgb(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                          "-vf", "scale=1:1:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return tuple(raw[:3])


def test_build_glues_screen_and_all_mics_by_timing(synthetic, tmp_path, caplog):
    record, fake_download = synthetic
    out = tmp_path / "out" / "Лекция.mp4"
    with caplog.at_level(logging.INFO, logger=LOG.name):
        M.build(tmp_path, record, out, LOG, download=fake_download)

    probed = M._probe(out)
    assert probed is not None and probed[0] == 1920 and probed[1] and abs(probed[2] - 30) < 0.5
    assert not out.with_name("Лекция.partial.mp4").exists()
    assert any("недоступен на сервере, пропускаю" in r.message for r in caplog.records)
    assert any(r.message.startswith("Сборка MP4: ") and "%" in r.message for r in caplog.records)
    # последняя строка сборки — 100%: дальше ffmpeg молча переписывает файл ради faststart
    assert [r.message for r in caplog.records if r.message.startswith("Сборка MP4: ")][-1].startswith("Сборка MP4: 100%")

    # картинка: чёрный до 10 с, экран с 10 до 25 (после cut — со смещением upTime=2, т.е. синий), потом чёрный
    for t, want in ((5, "black"), (11, "red"), (13, "blue"), (24, "blue"), (27, "black")):
        r, g, b = _rgb(out, t)
        assert g < 60, f"{t} с: камера не должна попадать в кадр ({r},{g},{b})"
        assert {"black": r < 30 and b < 30, "red": r > 180 and b < 60, "blue": b > 180 and r < 60}[want], (t, r, g, b)

    # звук: 440 Гц с 0 до 15 (upTime=5 пропускает 300 Гц), тишина 15–18, 880 Гц 18–28, тишина до конца
    rms, hz = _tone(out, 0.5, 11.5)
    assert rms > 0.05 and abs(hz - 440) < 10
    rms, hz = _tone(out, 12.5, 14.5)
    assert rms > 0.05 and abs(hz - 440) < 10
    assert _tone(out, 15.4, 17.6)[0] < 0.01
    rms, hz = _tone(out, 18.5, 27.5)
    assert rms > 0.05 and abs(hz - 880) < 10
    assert _tone(out, 28.4, 29.8)[0] < 0.01


@pytest.mark.parametrize("times, want", [
    ([0.5, 3, 7.2, 9.99], ["30%", "70%", "100%, дописываю файл..."]),  # запись 10 с
    ([0.2, 10], ["100%, дописываю файл..."]),        # быстрый ПК: всё между двумя отчётами
    ([0.2, 4], ["40%", "100%"]),                     # 99% не увидели, но ffmpeg сказал end
])
def test_merge_progress_always_reaches_100(tmp_path, monkeypatch, caplog, times, want):
    lines = [f"out_time_us={int(t * 1e6)}\nprogress=continue\n" for t in times] + ["progress=end\n"]

    class FakeProc:
        stdout = iter("".join(lines).splitlines(keepends=True))

        def wait(self):
            return 0

    monkeypatch.setattr(M.subprocess, "Popen", lambda *a, **k: FakeProc())
    plan = M.MergePlan(duration=10.0)
    with caplog.at_level(logging.INFO, logger=LOG.name):
        M._run_ffmpeg(plan, tmp_path, tmp_path / "out.mp4", LOG)
    assert [r.message.removeprefix("Сборка MP4: ") for r in caplog.records] == want


def test_build_cancel_kills_ffmpeg_and_leaves_no_file(synthetic, tmp_path):
    record, fake_download = synthetic
    stop = threading.Event()

    class StopOnMerge(logging.Handler):
        def emit(self, rec):
            if rec.getMessage()[len("Сборка MP4: "):][:1].isdigit():  # первый же процент сборки
                stop.set()

    log = logging.getLogger("test.mts.cancel")
    log.setLevel(logging.INFO)
    log.addHandler(StopOnMerge())
    out = tmp_path / "out" / "Лекция.mp4"
    with common.cancel_scope(stop), pytest.raises(common.Cancelled):
        M.build(tmp_path, record, out, log, download=fake_download)
    assert not out.exists() and not out.with_name("Лекция.partial.mp4").exists()


def test_download_cancel_keeps_part_for_resume(tmp_path):
    body = b"x" * (1 << 20)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stop = threading.Event()
    stop.set()
    try:
        with common.cancel_scope(stop), pytest.raises(common.Cancelled):
            M._download(f"http://127.0.0.1:{server.server_port}/piece.mp4", tmp_path, "1/1", LOG)
    finally:
        server.shutdown()
    assert not any(p.suffix == ".mp4" for p in tmp_path.iterdir())  # целого куска нет, .part докачается


def test_build_stops_instead_of_silently_dropping_a_piece(synthetic, tmp_path):
    record, fake_download = synthetic

    def flaky(url, directory, label, log):
        if url.endswith("mic2.mp4"):
            raise ConnectionError("обрыв")
        return fake_download(url, directory, label, log)
    out = tmp_path / "out.mp4"
    with pytest.raises(M.MtsLinkError, match="докачается с того же места"):
        M.build(tmp_path, record, out, LOG, download=flaky)
    assert not out.exists()


def _serve(handler_cls):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_download_404_means_piece_gone_and_416_means_part_complete(tmp_path, monkeypatch):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(416 if self.headers.get("Range") else 404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    server = _serve(Handler)
    try:
        base = f"http://127.0.0.1:{server.server_port}/api-storage/files/"
        with pytest.raises(M.PieceGone):
            M._download(base + "gone.mp4", tmp_path, "1/2", LOG)
        url = base + "done.mp4"
        part = tmp_path / (M._piece_name(url) + ".part")
        part.write_bytes(b"whole file")
        path = M._download(url, tmp_path, "2/2", LOG)
        assert path.read_bytes() == b"whole file" and not part.exists()
    finally:
        server.shutdown()


def test_missing_ffprobe_is_reported_not_treated_as_broken_file(tmp_path, monkeypatch):
    def no_ffprobe(*a, **kw):
        raise FileNotFoundError("ffprobe")
    monkeypatch.setattr(M.subprocess, "run", no_ffprobe)
    with pytest.raises(M.MtsLinkError, match="ffprobe"):
        M._probe(tmp_path / "x.mp4")


@pytest.mark.skipif(not HAS_FFMPEG, reason="нужен ffmpeg")
def test_filter_script_option_matches_ffmpeg_version():
    major = M._ffmpeg_major()
    args = M._filter_script_args("filter.txt")
    assert args == (["-filter_complex_script", "filter.txt"] if major is not None and major < 7
                    else ["-/filter_complex", "filter.txt"])


# --- веб: задачи из ссылок -----------------------------------------------------

from functools import partial  # noqa: E402
from queue import Queue  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

LINK = "https://my.mts-link.ru/146049682/24264533545/record-new/23673458754/record-file/2104961441"


@pytest.fixture()
def jobs_env(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "Q", Queue())
    monkeypatch.setattr(web, "JOBS", {})
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(web, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(M, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setitem(web.cfg["output"], "dir", str(tmp_path / "output"))
    created = []
    yield tmp_path, created
    for job_id in created:
        (web.ROOT / "runtime" / "logs" / f"job_{job_id}.log").unlink(missing_ok=True)


def test_link_job_waits_for_start_and_hides_secrets(jobs_env):
    tmp_path, _ = jobs_env
    client = TestClient(web.app)
    r = client.post("/api/mts-link", json={"url": LINK, "mode": "transcript", "session_id": "sessionId=s3cr3t"})
    assert r.status_code == 200
    job = r.json()
    assert job["status"] == "uploaded" and job["source"] == "mts" and job["mode"] == "transcript"
    assert not {"source_url", "session_id", "path", "video"} & job.keys() and job["has_video"] is False
    assert web.JOBS[job["id"]]["session_id"] == "s3cr3t"
    assert "s3cr3t" not in (tmp_path / "jobs.json").read_text(encoding="utf-8")
    assert "s3cr3t" not in client.get("/api/jobs").text and LINK not in client.get("/api/jobs").text


@pytest.mark.parametrize("payload", [
    {"url": "https://example.com/video.mp4"},
    {"url": LINK, "mode": "nope"},
    {"url": LINK, "session_id": "a b"},
])
def test_link_job_rejects_bad_input(jobs_env, payload):
    assert TestClient(web.app).post("/api/mts-link", json=payload).status_code == 400
    assert web.JOBS == {}


def test_upload_rejects_video_only_mode(jobs_env):
    r = TestClient(web.app).post("/api/upload", files={"file": ("пара.mp4", b"x", "video/mp4")}, data={"mode": "video"})
    assert r.status_code == 400 and "ссылками" in r.json()["detail"]


def test_link_start_checks_models_only_when_needed(jobs_env, monkeypatch):
    client = TestClient(web.app)
    monkeypatch.setattr(web, "_missing_model_roles", lambda settings: ["LLM"])
    full = client.post("/api/mts-link", json={"url": LINK, "mode": "full"}).json()
    assert client.post(f"/api/jobs/{full['id']}/start").status_code == 409  # до скачивания гигабайтов
    video = client.post("/api/mts-link", json={"url": LINK, "mode": "video"}).json()
    r = client.post(f"/api/jobs/{video['id']}/start")
    assert r.status_code == 200 and r.json()["status"] == "queued" and web.Q.get_nowait() == video["id"]


def test_uploaded_link_job_can_be_deleted(jobs_env):
    tmp_path, _ = jobs_env
    client = TestClient(web.app)
    job = client.post("/api/mts-link", json={"url": LINK}).json()
    (tmp_path / "uploads" / job["id"]).mkdir(parents=True)
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert job["id"] not in web.JOBS and not (tmp_path / "uploads" / job["id"]).exists()


def _patch_mts(monkeypatch, synthetic, seen):
    record, fake_download = synthetic

    def fake_fetch(link, session_id=None, timeout=60):
        seen.append(session_id)
        return record
    monkeypatch.setattr(M, "fetch_record", fake_fetch)
    monkeypatch.setattr(M, "build", partial(M.build, download=fake_download))


def _run(job_id, created):
    created.append(job_id)
    web.JOBS[job_id]["status"] = "queued"
    web._run_job(job_id)
    return web.JOBS[job_id]


def test_link_job_video_mode_end_to_end(jobs_env, synthetic, monkeypatch):
    tmp_path, created = jobs_env
    seen = []
    _patch_mts(monkeypatch, synthetic, seen)
    client = TestClient(web.app)
    job_id = client.post("/api/mts-link", json={"url": LINK, "mode": "video", "session_id": "s3cr3t"}).json()["id"]

    job = _run(job_id, created)

    assert job["status"] == "done", job.get("error")
    assert seen == ["s3cr3t"] and "session_id" not in job
    assert job["name"] == "Лекция"
    out = tmp_path / "output" / "Лекция" / "запись.mp4"
    assert job["out"] == str(out) and out.is_file() and abs(M._probe(out)[2] - 30) < 0.5
    assert not (tmp_path / "uploads" / job_id).exists() and not list((tmp_path / "cache").iterdir())
    listed = client.get("/api/jobs").json()[0]
    assert listed["has_video"] is True
    r = client.get(f"/api/jobs/{job_id}/download")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert "%D0%9B%D0%B5%D0%BA%D1%86%D0%B8%D1%8F.mp4" in r.headers["content-disposition"]  # Лекция.mp4
    assert client.get(f"/api/jobs/{job_id}/video").status_code == 200
    saved = (tmp_path / "jobs.json").read_text(encoding="utf-8")
    log_text = (web.ROOT / "runtime" / "logs" / f"job_{job_id}.log").read_text(encoding="utf-8")
    assert "s3cr3t" not in saved and "s3cr3t" not in log_text and "2104961441/record-file" not in log_text
    assert "source_url" not in job and "record-new" not in saved  # ссылка больше не хранится


def test_link_job_keeps_video_when_processing_fails(jobs_env, synthetic, monkeypatch):
    tmp_path, created = jobs_env
    _patch_mts(monkeypatch, synthetic, [])

    def broken(video, cfg, log):
        raise RuntimeError("ASR упал")
    monkeypatch.setattr(web, "extract_audio_track", broken)
    client = TestClient(web.app)
    job_id = client.post("/api/mts-link", json={"url": LINK, "mode": "audio"}).json()["id"]

    job = _run(job_id, created)

    assert job["status"] == "error" and "ASR упал" in job["error"]
    assert client.get("/api/jobs").json()[0]["has_video"] is True  # скачанную запись не теряем
    assert client.get(f"/api/jobs/{job_id}/video").status_code == 200
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert not (tmp_path / "uploads" / job_id).exists()


def test_job_log_is_closed_after_run_so_job_can_be_deleted(jobs_env, monkeypatch):
    _, created = jobs_env
    monkeypatch.setattr(web, "extract_audio_track", lambda video, cfg, log: (_ for _ in ()).throw(RuntimeError("x")))
    video = jobs_env[0] / "lesson.mp4"
    video.write_bytes(b"x")
    web.JOBS["log01"] = {"id": "log01", "name": "lesson.mp4", "path": str(video), "mode": "audio",
                         "status": "queued", "stage": "", "created": "2026-10-15 12:00:00",
                         "started": None, "finished": None, "out": None, "error": None}
    created.append("log01")
    web._run_job("log01")
    assert web.logging.getLogger("videonotes.job.log01").handlers == []  # файл лога не держится открытым
    log_file = web.ROOT / "runtime" / "logs" / "job_log01.log"
    assert log_file.exists()
    assert TestClient(web.app).delete("/api/jobs/log01").status_code == 200
    assert not log_file.exists()


def test_link_job_reports_access_error(jobs_env, monkeypatch):
    _, created = jobs_env

    def forbidden(link, session_id=None, timeout=60):
        raise M.MtsLinkError("Доступ к записи запрещён: запись закрытая, а вход не указан или устарел.")
    monkeypatch.setattr(M, "fetch_record", forbidden)
    client = TestClient(web.app)
    job_id = client.post("/api/mts-link", json={"url": LINK, "session_id": "old"}).json()["id"]

    job = _run(job_id, created)

    assert job["status"] == "error" and "вход не указан или устарел" in job["error"]
    assert "session_id" not in job and "source_url" not in job
    assert client.get("/api/jobs").json()[0]["has_video"] is False


def test_link_job_audio_mode_end_to_end(jobs_env, synthetic, monkeypatch):
    pytest.importorskip("torch")
    pytest.importorskip("soundfile")
    tmp_path, created = jobs_env
    _patch_mts(monkeypatch, synthetic, [])
    job_id = TestClient(web.app).post("/api/mts-link", json={"url": LINK, "mode": "audio"}).json()["id"]

    job = _run(job_id, created)

    assert job["status"] == "done", job.get("error")
    folder = tmp_path / "output" / "Лекция"
    assert job["out"] == str(folder / "audio.wav") and (folder / "audio.wav").is_file()
    assert (folder / "запись.mp4").is_file() and job["video"] == str(folder / "запись.mp4")
    assert not (tmp_path / "uploads" / job_id).exists()
