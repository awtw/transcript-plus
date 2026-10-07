//! Export rendering. SRT/VTT need the caption engine (`make_captions`, cue split/merge), still to be ported.
use unicode_segmentation::UnicodeSegmentation;

use crate::domain::{timestamp, Document};

pub fn export_txt(doc: &Document) -> String {
    let blocks: Vec<String> = doc
        .segments
        .iter()
        .map(|s| {
            let speaker = if s.speaker.is_empty() { "講者" } else { &s.speaker };
            format!("[{}] {}\n{}", timestamp(s.start_ms, '.'), speaker, s.text)
        })
        .collect();
    blocks.join("\n\n") + "\n"
}

/// One wrap at most; text beyond two lines is kept, never dropped (the caption warnings flag it).
pub fn wrap_caption(text: &str, max_chars: usize) -> String {
    let flat = text.replace(['\r', '\n'], " ");
    let chars: Vec<&str> = flat.trim().graphemes(true).collect();
    if chars.len() <= max_chars {
        return chars.concat();
    }
    let midpoint = max_chars.min((chars.len() + 1) / 2);
    let spaces = chars.iter().take(max_chars + 1).enumerate().filter(|(i, c)| c.trim().is_empty() && *i > max_chars / 3).map(|(i, _)| i);
    let cut = spaces.min_by_key(|i| i.abs_diff(midpoint)).unwrap_or(midpoint);
    format!("{}\n{}", chars[..cut].concat().trim_end(), chars[cut..].concat().trim_start())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn short_text_is_not_wrapped_and_long_text_keeps_every_char() {
        assert_eq!(wrap_caption("下週上線", 18), "下週上線");
        let long = "一二三四五六七八九十一二三四五六七八九十";
        let wrapped = wrap_caption(long, 10);
        assert_eq!(wrapped.replace('\n', ""), long);
        assert_eq!(wrapped.lines().count(), 2);
    }

    #[test]
    fn newlines_in_cue_text_never_make_blank_lines() {
        assert!(!wrap_caption("甲\n\n乙", 18).contains("\n\n"));
    }

    #[test]
    fn txt_uses_default_speaker() {
        let json = r#"{"schema_version":1,"duration_ms":5000,"segments":[{"id":"a","start_ms":61000,"end_ms":62000,"text":"嗨"}]}"#;
        let doc: Document = serde_json::from_str(json).unwrap();
        assert_eq!(export_txt(&doc), "[00:01:01.000] 講者\n嗨\n");
    }
}
