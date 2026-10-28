from app.services import router, summarizer, token_saver
from app.services.token_saver import apply, dedupe, normalize

CODE = "```python\ndef f(x):\n\n\n\n    return x  *  2   # spasi dijaga\n```"
TABLE = "| a  |  b |\n|----|----|\n| 1  |  2 |"


def msgs(*pairs):
    return [{"role": r, "content": c} for r, c in pairs]


def test_plain_text_whitespace_cleaned():
    assert normalize("Halo   dunia\t\tini\n\n\n\n\nbaris baru") == "Halo dunia ini\n\nbaris baru"


def test_code_block_untouched():
    text = f"Lihat   ini:\n{CODE}\n\n\n\nselesai"
    out = normalize(text)
    assert CODE in out
    assert out.startswith("Lihat ini:")


def test_inline_code_and_table_untouched():
    text = f"pakai `a  =  b`   saja\n{TABLE}"
    out = normalize(text)
    assert "`a  =  b`" in out
    assert TABLE in out


def test_numbers_and_urls_untouched():
    text = "Harga   Rp 1.250.000,50 di https://contoh.id/a?b=1&c=2   sekarang"
    out = normalize(text)
    assert "1.250.000,50" in out and "https://contoh.id/a?b=1&c=2" in out


def test_repeated_sentence_removed_inside_message():
    text = "Tolong buatkan ringkasan laporan ini. Tolong buatkan ringkasan laporan ini. Terima kasih."
    assert normalize(text).count("Tolong buatkan ringkasan laporan ini.") == 1


def test_pleasantry_stripped_from_history_only_when_content_remains():
    assert normalize("Halo, terima kasih! Jelaskan TCP.", strip_pleasantries=True) == "Jelaskan TCP."
    assert normalize("Terima kasih!", strip_pleasantries=True) == "Terima kasih!"


def test_identical_messages_deduped_but_current_prompt_kept():
    history = msgs(
        ("user", "Apa itu Docker?"),
        ("assistant", "Docker adalah platform kontainer."),
        ("user", "Apa itu Docker?"),
        ("assistant", "Docker adalah platform kontainer."),
        ("user", "Apa itu Docker?"),
    )
    out = dedupe(history)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[-1]["content"] == "Apa itu Docker?"


def test_near_duplicate_removed_but_different_numbers_kept():
    history = msgs(
        ("user", "Berapa harga paket A untuk 10 orang?"),
        ("assistant", "Rp 500.000"),
        ("user", "Berapa harga paket A untuk 10 orang ya?"),
        ("assistant", "Rp 500.000"),
        ("user", "Berapa harga paket A untuk 12 orang?"),
    )
    out = dedupe(history)
    assert sum("10 orang" in m["content"] for m in out) == 1
    assert out[-1]["content"].endswith("12 orang?")


def test_code_messages_never_deduped():
    history = msgs(
        ("user", CODE), ("assistant", "ok"), ("user", CODE + " "), ("assistant", "ok2"), ("user", "lanjut")
    )
    out = dedupe(history)
    assert sum(CODE in m["content"] for m in out) == 2


def test_aggressive_drops_pleasantry_only_turns():
    history = msgs(("user", "makasih"), ("assistant", "sama-sama"), ("user", "Jelaskan DNS"))
    assert apply(history, "aggressive").messages == msgs(("user", "Jelaskan DNS"))


def test_sliding_window_and_summary_injected():
    history = []
    for i in range(30):
        history += msgs(
            ("user", f"pertanyaan nomor {i} tentang topik {i * 7}"), ("assistant", f"jawaban {i}")
        )
    history += msgs(("user", "pertanyaan terakhir"))
    out = apply(history, "normal", system_prompt="Kamu asisten.", summary="ringkasan lama")
    roles = [m["role"] for m in out.messages]
    assert roles[:2] == ["system", "system"]
    assert "ringkasan lama" in out.messages[1]["content"]
    assert len(out.messages) <= 2 + token_saver.MODES["normal"]["window"]
    assert out.messages[2]["role"] == "user"
    assert out.messages[-1]["content"] == "pertanyaan terakhir"
    assert out.tokens_saved > 0


def test_off_mode_is_passthrough():
    history = msgs(("user", "a   b"), ("assistant", "c"), ("user", "a   b"))
    out = apply(history, "off")
    assert out.messages == history and out.tokens_saved == 0


def test_benchmark_repetitive_history_saves_tokens():
    turn = msgs(
        ("user", "Halo! Tolong   jelaskan   cara deploy aplikasi FastAPI ke VPS.\n\n\n\n"),
        (
            "assistant",
            "Gunakan Docker   Compose dan   Caddy untuk HTTPS.   "
            "Gunakan Docker   Compose dan   Caddy untuk HTTPS.",
        ),
    )
    history = turn * 8 + msgs(("user", "Bagaimana dengan backup database?"))
    out = apply(history, "normal")
    pct = out.tokens_saved / out.tokens_before
    assert pct > 0.5, f"only saved {pct:.0%}"


def test_summarizer_trigger():
    run, upto = summarizer.needs_summary(30, "normal", 0)
    assert run and upto == 30 - token_saver.MODES["normal"]["window"]
    assert summarizer.needs_summary(30, "normal", upto) == (False, upto)
    assert summarizer.needs_summary(5, "normal", 0)[0] is False
    assert summarizer.needs_summary(100, "off", 0)[0] is False
    req = summarizer.build_request("lama", msgs(("user", "x")))
    assert "lama" in req[1]["content"]


def test_router_classify_and_plan():
    assert router.classify("tolong debug error python ini") == "coding"
    assert router.classify("Buat analisis strategi pemasaran") == "complex"
    assert router.classify("halo apa kabar") == "light"
    cands = [
        router.Candidate("anthropic", "claude-sonnet-4-5", "strong"),
        router.Candidate("groq", "llama-3.1-8b-instant", "cheap"),
        router.Candidate("gemini", "gemini-2.5-flash", "cheap"),
    ]
    assert router.plan("auto", "fix bug di kode python", cands, [], True)[0].provider == "anthropic"
    assert router.plan("auto", "halo", cands, [], True)[0].tier == "cheap"
    ordered = router.plan("auto", "halo", cands, ["gemini/gemini-2.5-flash"], True)
    assert ordered[0].ref == "gemini/gemini-2.5-flash"
    manual = router.plan("groq/llama-3.1-8b-instant", "x", cands, [], False)
    assert [c.ref for c in manual] == ["groq/llama-3.1-8b-instant"]
    assert len(router.plan("groq/llama-3.1-8b-instant", "x", cands, [], True)) == 3
