use std::path::{Component, Path};

pub fn validate_relative_artifact_path(path: &Path) -> Result<(), String> {
    if path.as_os_str().is_empty() {
        return Err("artifact path must not be empty".to_owned());
    }

    if path.is_absolute() {
        return Err("artifact path must be relative".to_owned());
    }

    if path
        .components()
        .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err("artifact path must contain only normal path components".to_owned());
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::validate_relative_artifact_path;

    #[test]
    fn rejects_parent_traversal() {
        assert!(validate_relative_artifact_path(Path::new("../state.sqlite")).is_err());
    }

    #[test]
    fn accepts_scoped_relative_path() {
        assert!(validate_relative_artifact_path(Path::new("b/objects/message.bin")).is_ok());
    }
}
