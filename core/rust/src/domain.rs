//! Transcript document rules. Timing is never inferred from character count.
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::HashSet;
use std::sync::OnceLock;

use crate::error::{err, require, Result};

pub const MAX_DURATION_MS: i64 = 7_200_000;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Word {
    pub id: String,
    pub text: String,
    pub start_ms: i64,
    pub end_ms: i64,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Segment {
    pub id: String,
    pub start_ms: i64,
    pub end_ms: i64,
    pub text: String,
    #[serde(default)]
    pub raw_text: String,
    #[serde(default)]
    pub words: Vec<Word>,
    #[serde(default)]
    pub alignment_status: String,
    #[serde(default)]
    pub speaker: String,
    // Fields owned by other modules (speaker analysis, ...) round-trip untouched.
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Document {
    pub schema_version: i64,
    pub duration_ms: i64,
    pub segments: Vec<Segment>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

fn lexical_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[\p{P}\p{Z}\s]").unwrap())
}

/// Text with punctuation and whitespace removed; the unit used to align edited text with timed words.
pub fn lexical(text: &str) -> String {
    lexical_re().replace_all(text, "").into_owned()
}

pub fn valid_time(start: i64, end: i64, duration: i64) -> bool {
    0 <= start && start < end && end <= duration
}

pub fn validate_document(doc: &Document) -> Result<()> {
    require(doc.schema_version == 1, "INVALID_DOCUMENT", "不支援的逐字稿格式。")?;
    require(0 < doc.duration_ms && doc.duration_ms <= MAX_DURATION_MS, "INVALID_TIMING", "影音長度必須介於 0 與 120 分鐘。")?;
    require(doc.segments.len() <= 50_000, "INVALID_DOCUMENT", "逐字稿段落數超過限制。")?;
    let mut seen = HashSet::new();
    for s in &doc.segments {
        require(!s.id.is_empty() && seen.insert(s.id.as_str()), "INVALID_DOCUMENT", "逐字稿段落識別碼重複或遺失。")?;
        require(valid_time(s.start_ms, s.end_ms, doc.duration_ms), "INVALID_TIMING", "逐字稿時間超出影音範圍。")?;
        require(!s.text.trim().is_empty() && s.text.chars().count() <= 20_000, "INVALID_DOCUMENT", "逐字稿文字不可空白或超過 20,000 字元。")?;
    }
    Ok(())
}

pub fn edit_segment(doc: &Document, segment_id: &str, text: &str, speaker: Option<&str>) -> Result<Document> {
    let mut result = doc.clone();
    let Some(segment) = result.segments.iter_mut().find(|s| s.id == segment_id) else {
        return err("NOT_FOUND", "找不到逐字稿段落。");
    };
    require(!text.trim().is_empty() && text.chars().count() <= 20_000, "INVALID_DOCUMENT", "文字不可空白或超過 20,000 字元。")?;
    segment.text = text.trim().to_string();
    // Restoring the original text restores timing only when the full original word map is valid.
    let joined: String = segment.words.iter().map(|w| w.text.as_str()).collect();
    let complete = !segment.words.is_empty() && lexical(&joined) == lexical(&segment.raw_text);
    segment.alignment_status = if complete && lexical(text) == lexical(&segment.raw_text) { "valid" } else { "dirty" }.into();
    if let Some(name) = speaker {
        require(name.chars().count() <= 80, "INVALID_DOCUMENT", "講者名稱最多 80 字。")?;
        if name.trim() != segment.speaker {
            // A typed name is final: later speaker analysis must not overwrite it.
            segment.extra.insert("speaker_source".into(), Value::String("manual".into()));
            segment.extra.insert("needs_confirmation".into(), Value::Bool(false));
        }
        segment.speaker = name.trim().to_string();
    }
    validate_document(&result)?;
    Ok(result)
}

#[derive(Debug, PartialEq)]
pub struct Span<'a> {
    /// Byte offset in `segment.text` where this word ends.
    pub end: usize,
    pub word: &'a Word,
}

/// Map current text (including punctuation edits) to the original timed words; empty when unreliable.
pub fn word_spans(segment: &Segment) -> Vec<Span<'_>> {
    if segment.alignment_status != "valid" {
        return vec![];
    }
    let text = &segment.text;
    let positions: Vec<usize> = text.char_indices().filter(|(_, c)| !lexical(&c.to_string()).is_empty()).map(|(i, _)| i).collect();
    let joined: String = segment.words.iter().map(|w| w.text.as_str()).collect();
    if lexical(&joined) != lexical(text) {
        return vec![];
    }
    let (mut spans, mut consumed, mut previous_end) = (vec![], 0usize, segment.start_ms);
    for word in &segment.words {
        let count = lexical(&word.text).chars().count();
        if count == 0 {
            continue;
        }
        if !valid_time(word.start_ms, word.end_ms, segment.end_ms) || word.start_ms < previous_end {
            return vec![];
        }
        consumed += count;
        let end = positions.get(consumed).copied().unwrap_or(text.len());
        spans.push(Span { end, word });
        previous_end = word.end_ms;
    }
    spans
}

pub fn timestamp(ms: i64, sep: char) -> String {
    let (h, rest) = (ms / 3_600_000, ms % 3_600_000);
    let (m, rest) = (rest / 60_000, rest % 60_000);
    format!("{h:02}:{m:02}:{:02}{sep}{:03}", rest / 1000, rest % 1000)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn word(id: &str, text: &str, s: i64, e: i64) -> Word {
        Word { id: id.into(), text: text.into(), start_ms: s, end_ms: e, extra: Map::new() }
    }

    pub fn doc() -> Document {
        Document {
            schema_version: 1,
            duration_ms: 10_000,
            segments: vec![Segment {
                id: "seg1".into(), start_ms: 1200, end_ms: 2600, text: "下週上線。".into(), raw_text: "下週上線".into(),
                words: vec![word("w1", "下週", 1200, 1800), word("w2", "上線", 1900, 2600)],
                alignment_status: "valid".into(), speaker: String::new(), extra: Map::new(),
            }],
            extra: Map::new(),
        }
    }

    #[test]
    fn valid_document_passes_and_bad_timing_fails() {
        assert!(validate_document(&doc()).is_ok());
        let mut d = doc();
        d.segments[0].end_ms = 20_000;
        assert_eq!(validate_document(&d).unwrap_err().code, "INVALID_TIMING");
        let mut d = doc();
        d.segments[0].text = "  ".into();
        assert_eq!(validate_document(&d).unwrap_err().code, "INVALID_DOCUMENT");
    }

    #[test]
    fn punctuation_edit_keeps_alignment_word_edit_dirties_it() {
        let kept = edit_segment(&doc(), "seg1", "下週，上線！", None).unwrap();
        assert_eq!(kept.segments[0].alignment_status, "valid");
        let dirty = edit_segment(&doc(), "seg1", "下週五上線", None).unwrap();
        assert_eq!(dirty.segments[0].alignment_status, "dirty");
        assert!(word_spans(&dirty.segments[0]).is_empty());
    }

    #[test]
    fn typed_speaker_is_marked_manual() {
        let d = edit_segment(&doc(), "seg1", "下週上線。", Some("小王")).unwrap();
        assert_eq!(d.segments[0].speaker, "小王");
        assert_eq!(d.segments[0].extra["speaker_source"], "manual");
    }

    #[test]
    fn word_spans_follow_punctuation_edits() {
        let d = edit_segment(&doc(), "seg1", "下週，上線！", None).unwrap();
        let spans = word_spans(&d.segments[0]);
        assert_eq!(spans.len(), 2);
        assert_eq!(&d.segments[0].text[..spans[0].end], "下週，");
        assert_eq!(spans[1].word.start_ms, 1900);
    }

    #[test]
    fn unknown_python_fields_round_trip() {
        let json = r#"{"schema_version":1,"duration_ms":5000,"segments":[{"id":"a","start_ms":0,"end_ms":1000,"text":"嗨","speaker_group":"g1"}],"title":"x"}"#;
        let d: Document = serde_json::from_str(json).unwrap();
        let back: Value = serde_json::to_value(&d).unwrap();
        assert_eq!(back["segments"][0]["speaker_group"], "g1");
        assert_eq!(back["title"], "x");
    }

    #[test]
    fn timestamp_format() {
        assert_eq!(timestamp(3_723_456, ','), "01:02:03,456");
        assert_eq!(timestamp(61_000, '.'), "00:01:01.000");
    }
}
