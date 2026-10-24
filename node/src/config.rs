use crate::error::{Code, Error, Result};
use serde::Deserialize;
use std::{
    io::Read,
    path::{Component, PathBuf},
};

pub const MAX_CONFIG_BYTES: u64 = 16 * 1024;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub version: u32,
    pub data_directory: PathBuf,
    pub limits: Limits,
}

/// First-batch application ceilings, independent of the I5 execution budget.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Limits {
    pub payload_count: u32,
    pub payload_bytes: u64,
    pub history_count: u32,
    pub history_bytes: u64,
    pub control_count: u32,
    pub control_bytes: u64,
    pub record_count: u32,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            payload_count: 2048,
            payload_bytes: 16 * 1024 * 1024,
            history_count: 10000,
            history_bytes: 64 * 1024 * 1024,
            control_count: 4096,
            control_bytes: 8 * 1024 * 1024,
            record_count: 16384,
        }
    }
}
impl Limits {
    pub fn validate(&self) -> Result<()> {
        let max = Self::default();
        if self.payload_count == 0
            || self.payload_count > max.payload_count
            || self.payload_bytes == 0
            || self.payload_bytes > max.payload_bytes
            || self.history_count == 0
            || self.history_count > max.history_count
            || self.history_bytes == 0
            || self.history_bytes > max.history_bytes
            || self.control_count == 0
            || self.control_count > max.control_count
            || self.control_bytes == 0
            || self.control_bytes > max.control_bytes
            || self.record_count == 0
            || self.record_count > max.record_count
        {
            return Err(Error::new(Code::InvalidInput, "resource ceilings"));
        }
        Ok(())
    }
}
impl Config {
    pub fn read(reader: impl Read) -> Result<Self> {
        let mut bytes = Vec::new();
        reader.take(MAX_CONFIG_BYTES + 1).read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_CONFIG_BYTES {
            return Err(Error::new(Code::InvalidInput, "config size"));
        }
        let config: Self = serde_json::from_slice(&bytes)
            .map_err(|e| Error::source_error(Code::InvalidInput, "config JSON", e))?;
        config.validate()?;
        Ok(config)
    }
    pub fn validate(&self) -> Result<()> {
        if self.version != 1 {
            return Err(Error::new(Code::UnsupportedVersion, "config version"));
        }
        if !self.data_directory.is_absolute()
            || self.data_directory.components().count() < 3
            || self
                .data_directory
                .components()
                .any(|c| matches!(c, Component::ParentDir | Component::CurDir))
        {
            return Err(Error::new(Code::InvalidInput, "data directory"));
        }
        self.limits.validate()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn config_rejects_ambiguous_or_unbounded_input() {
        let good = include_str!("../config.example.json");
        assert!(Config::read(good.as_bytes()).is_ok());
        for bad in [
            good.replace("\"version\": 1", "\"version\": 1, \"version\": 1"),
            good.replace("\"version\": 1", "\"version\": 2"),
            good.replace(
                "\"version\": 1",
                "\"secret\": \"never-echo\", \"version\": 1",
            ),
            good.replace("/var/lib/radishlink", "/"),
            good.replace("2048", "0"),
        ] {
            let err = Config::read(bad.as_bytes()).unwrap_err();
            assert!(!format!("{err:?}").contains("never-echo"));
        }
        assert!(Config::read(vec![b' '; 16385].as_slice()).is_err());
    }
}
