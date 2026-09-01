"""Сводка: map-reduce по транскрипту + описания кадров -> конспект."""
from common import fmt_ts

MAP_PROMPT = """Ты — ассистент по конспектированию видео. Ниже фрагмент транскрипции (таймкоды [мм:сс]) и описания кадров в эти моменты.

Составь выжимку этого фрагмента:
- ключевые тезисы и факты (с таймкодами [мм:сс])
- определения и термины
- примеры, цифры, упомянутые инструменты/код
Формат: markdown-списки. Только то, что есть в фрагменте. Без воды.

=== ФРАГМЕНТ ТРАНСКРИПЦИИ ===
{transcript}

=== ОПИСАНИЯ КАДРОВ ===
{frames}
"""

REDUCE_PROMPT = """Ты — ассистент по конспектированию видео. Ниже выжимки всех фрагментов видео и список важных моментов с экрана.

Собери единый конспект. Начни ответ сразу с заголовка «## TL;DR». Не делай оглавление, не дублируй заголовки, не пиши вступлений. Используй ровно эти четыре заголовка, в этом порядке, без других заголовков уровня ##:

## TL;DR
3-5 пунктов: о чём видео в целом.

## Конспект
Разделы по темам (### заголовок [мм:сс]). Внутри — тезисы, факты, термины с таймкодами [мм:сс].

## Ключевые термины
Строки вида: **термин** — значение [мм:сс]

## Важные цитаты
2-5 точных цитат из разговора с таймкодами.

Пиши на русском, точно, без воды. Используй только данные из выжимок. Если данных для раздела мало — напиши одно-два предложения, не выдумывай.

=== ВЫЖИМКИ ФРАГМЕНТОВ ===
{summaries}

=== ВАЖНЫЕ МОМЕНТЫ С ЭКРАНА ===
{frames}
"""


def chunk_transcript(lines: list[tuple[float, str]], max_words: int = 2000
                     ) -> list[list[tuple[float, str]]]:
    """Группировка строк транскрипта [start_sec, text] в куски ~max_words."""
    chunks: list[list[tuple[float, str]]] = []
    cur: list[tuple[float, str]] = []
    words = 0
    for line in lines:
        n = len(line[1].split())
        if words + n > max_words and cur:
            chunks.append(cur)
            cur, words = [], 0
        cur.append(line)
        words += n
    if cur:
        chunks.append(cur)
    return chunks


def render_chunk(chunk: list[tuple[float, str]]) -> str:
    return "\n".join(f"[{fmt_ts(t)}] {text}" for t, text in chunk)


def render_frames_for_range(frames: list[dict], t0: float, t1: float) -> str:
    sel = [f for f in frames if t0 <= f["t"] < t1]
    if not sel:
        return "(нет кадров в этом диапазоне)"
    return "\n".join(f"[{fmt_ts(f['t'])}] {f['desc']}" for f in sel)


def summarize(llm, transcript_lines: list[tuple[float, str]],
              frames: list[dict], log, max_words: int = 2000) -> str:
    """Map-reduce. Возвращает markdown-тело конспекта (без frontmatter)."""
    chunks = chunk_transcript(transcript_lines, max_words)
    if not chunks:
        return "## TL;DR\n- Речь не обнаружена; конспект собран по кадрам.\n"
    log.info("Сводка: %d фрагментов по ~%d слов", len(chunks), max_words)
    summaries = []
    for i, chunk in enumerate(chunks, 1):
        t0, t1 = chunk[0][0], chunk[-1][0]
        prompt = MAP_PROMPT.format(
            transcript=render_chunk(chunk),
            frames=render_frames_for_range(frames, t0, t1),
        )
        log.info("  выжимка %d/%d ...", i, len(chunks))
        summaries.append(f"### Фрагмент {i} [{fmt_ts(t0)}–{fmt_ts(t1)}]\n{llm.chat(prompt)}")
    important = [f for f in frames if f.get("importance") == "высокая"]
    if not important:
        important = frames[:10]
    reduce_prompt = REDUCE_PROMPT.format(
        summaries="\n\n".join(summaries),
        frames="\n".join(f"[{fmt_ts(f['t'])}] {f['desc']}" for f in important) or "(нет)",
    )
    log.info("  финальная сборка конспекта ...")
    return llm.chat(reduce_prompt)