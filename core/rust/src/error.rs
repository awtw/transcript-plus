use thiserror::Error;

/// `code` mirrors the Python `AppError` codes so the UI can map them identically on every platform.
#[derive(Debug, Error, PartialEq)]
#[error("{code}: {message}")]
pub struct CoreError {
    pub code: &'static str,
    pub message: String,
}

pub type Result<T> = std::result::Result<T, CoreError>;

pub fn err<T>(code: &'static str, message: &str) -> Result<T> {
    Err(CoreError { code, message: message.to_string() })
}

pub fn require(ok: bool, code: &'static str, message: &str) -> Result<()> {
    if ok { Ok(()) } else { err(code, message) }
}
