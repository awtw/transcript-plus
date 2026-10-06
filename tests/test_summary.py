import pytest

from transcript_plus import summary
from transcript_plus.errors import AppError


def source(*texts):
    return [{"segment_index": i, "text": t} for i, t in enumerate(texts)]


def item(**over):
    base = {"kind": "summary", "text": "重點", "owner": None, "deadline": None, "commitment_quote": None,
            "citation_indices": [0]}
    return {"items": [base | over]}


def test_chunks_keep_every_character_and_slice_long_paragraphs():
    segments = [{"text": "甲" * 4000}, {"text": "乙"}, {"text": "  "}]
    batches = list(summary.chunks(segments, limit=2500))
    joined = "".join(e["text"] for b in batches for e in b)
    assert joined == "甲" * 4000 + "乙"
    assert len(batches) > 1


def test_citations_come_from_source_not_model():
    result = summary.citation_payload(item(), source("今天開會。"))
    assert result[0]["citations"] == [{"segment_index": 0, "quote": "今天開會。"}]


def test_unknown_citation_index_is_rejected():
    with pytest.raises(ValueError):
        summary.citation_payload(item(citation_indices=[5]), source("今天開會。"))


def test_unsupported_owner_and_deadline_are_dropped():
    payload = item(kind="action", owner="小李", deadline="下週", commitment_quote="我會處理",
                   citation_indices=[0])
    result = summary.citation_payload(payload, source("小王：我會處理，週五前。"))
    assert result[0]["owner"] is None and result[0]["deadline"] is None


def test_supported_owner_is_kept():
    payload = item(kind="action", owner="小王", deadline="週五前", commitment_quote="我會處理")
    result = summary.citation_payload(payload, source("小王：我會處理，週五前。"))
    assert (result[0]["owner"], result[0]["deadline"]) == ("小王", "週五前")


def test_decision_without_quoted_commitment_is_rejected():
    with pytest.raises(ValueError, match="commitment_quote"):
        summary.citation_payload(item(kind="decision", commitment_quote="原文沒有的話"), source("我們討論一下。"))
    with pytest.raises(ValueError):
        summary.citation_payload(item(kind="action"), source("我們討論一下。"))


def test_invented_quote_in_strict_validation_fails():
    bad = {"items": [{"kind": "summary", "text": "x", "owner": None, "deadline": None,
                      "citations": [{"segment_index": 0, "quote": "編造"}]}]}
    with pytest.raises(ValueError, match="不在原文"):
        summary.validate_items(bad, source("真實原文"))


class Fake:
    def __init__(self, behaviour):
        self.behaviour, self.calls = behaviour, []

    def complete(self, batch, repair=None):
        self.calls.append((batch, repair))
        return self.behaviour(batch, repair, len(self.calls))


def cited(batch):
    return [{"kind": "summary", "text": "重點", "owner": None, "deadline": None, "commitment_quote": None,
             "citations": [{"segment_index": batch[0]["segment_index"], "quote": batch[0]["text"]}]}]


def test_overflow_splits_the_batch_and_covers_everything():
    def behaviour(batch, repair, n):
        if len(batch) > 1:
            raise summary.ContextOverflow("太長")
        return cited(batch)
    segments = [{"text": f"第{i}段"} for i in range(4)]
    out = summary.summarize(segments, Fake(behaviour))
    assert out["covered_segment_indices"] == [0, 1, 2, 3] and len(out["items"]) == 4


def test_one_repair_attempt_then_failure_surfaces():
    def behaviour(batch, repair, n):
        raise ValueError("格式錯")
    client = Fake(behaviour)
    with pytest.raises(ValueError):
        summary.summarize([{"text": "內容"}], client)
    assert [c[1] for c in client.calls] == [None, "格式錯"]


def test_attach_sources_uses_stable_segment_ids():
    segments = [{"id": "seg-a", "start_ms": 100, "end_ms": 900, "text": "原文"}]
    items = summary.attach_sources(cited([{"segment_index": 0, "text": "原文"}]), segments, lambda: "id-1")
    assert items[0]["id"] == "id-1"
    assert items[0]["citations"] == [{"segment_id": "seg-a", "start_ms": 100, "end_ms": 900, "quote": "原文"}]


def test_markdown_groups_by_kind_and_keeps_citations(service):
    project = service.store.project("p1")
    project["summary"] = {"model": "m", "source_revision": 1, "items": [
        {"id": "1", "kind": "action", "text": "修缺陷", "owner": "小王", "deadline": "週五", "commitment_quote": "x",
         "citations": [{"segment_id": "segment-a", "start_ms": 3661000, "end_ms": 3670000, "quote": "我來修"}]}]}
    text = summary.to_markdown(project)
    assert "## 待辦" in text and "負責人：小王；期限：週五" in text and "[01:01:01] 「我來修」" in text


def test_summary_goes_stale_when_transcript_changes(service):
    service.store.save_summary("p1", {"source_revision": 1, "items": [], "model": "m"})
    assert service.get_project("p1")["summary_stale"] is False
    service.dispatch("transcript.edit", {"project_id": "p1", "segment_id": "segment-a", "text": "改過的內容。", "expected_revision": 1})
    project = service.get_project("p1")
    assert project["summary_stale"] is True
    with pytest.raises(AppError) as error:
        service.dispatch("export.render", {"project_id": "p1", "expected_revision": project["revision"], "format": "md"})
    assert error.value.code == "STALE_SUMMARY"


def test_summary_job_requires_model_and_server(service):
    with pytest.raises(AppError) as error:
        service.dispatch("summary.start", {"project_id": "p1"})
    assert error.value.code == "MODEL_MISSING"


def test_gguf_model_must_have_magic(tmp_path, service):
    fake = tmp_path / "x.gguf"
    fake.write_bytes(b"NOPE" + b"0" * 10)
    with pytest.raises(AppError) as error:
        service.dispatch("model.configure_summary", {"path": str(fake)})
    assert error.value.code == "MODEL_CORRUPT"
    fake.write_bytes(b"GGUF" + b"0" * 10)
    status = service.dispatch("model.configure_summary", {"path": str(fake)})
    assert status["summary_model"]["name"] == "x" and status["summary_model"]["present"]
