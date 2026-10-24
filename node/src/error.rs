use std::{error::Error as StdError, fmt};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Code {
    InvalidInput,
    UnsupportedVersion,
    Conflict,
    Quota,
    Expired,
    TimeUncertain,
    StoreUnavailable,
    StoreCorrupt,
    OutcomeUnknown,
    SecurityUnavailable,
    Busy,
    Stopped,
}

/// Display is safe for the CLI; the retained source is for controlled diagnostics only.
pub struct Error {
    pub code: Code,
    pub operation: &'static str,
    source: Option<Box<dyn StdError + Send + Sync>>,
}

impl Error {
    pub fn new(code: Code, operation: &'static str) -> Self {
        Self {
            code,
            operation,
            source: None,
        }
    }
    pub fn source_error(
        code: Code,
        operation: &'static str,
        source: impl StdError + Send + Sync + 'static,
    ) -> Self {
        Self {
            code,
            operation,
            source: Some(Box::new(source)),
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}: {}", self.code, self.operation)
    }
}
impl fmt::Debug for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}
impl StdError for Error {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        self.source
            .as_ref()
            .map(|s| s.as_ref() as &(dyn StdError + 'static))
    }
}
impl From<rusqlite::Error> for Error {
    fn from(e: rusqlite::Error) -> Self {
        Self::source_error(Code::StoreUnavailable, "sqlite operation", e)
    }
}
impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Self::source_error(Code::StoreUnavailable, "filesystem operation", e)
    }
}
pub type Result<T> = std::result::Result<T, Error>;
