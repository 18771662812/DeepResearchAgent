from app.agent.sources import SourceRegistry


def test_add_dedups_by_normalized_url():
    reg = SourceRegistry()
    a = reg.add("https://example.com/page/", "A")
    b = reg.add("https://example.com/page#section", "B")
    c = reg.add("https://example.com/other", "C")
    assert a.id == b.id == 1
    assert c.id == 2


def test_cited_in_parses_various_formats_and_ignores_unknown_ids():
    reg = SourceRegistry()
    for i in range(3):
        reg.add(f"https://example.com/{i}", str(i))
    text = "结论一 [2]。结论二 [1, 3]。结论三 [3][2]。编造的 [99]。"
    assert [s.id for s in reg.cited_in(text)] == [1, 2, 3]


def test_cited_in_empty():
    assert SourceRegistry().cited_in("没有引用") == []
