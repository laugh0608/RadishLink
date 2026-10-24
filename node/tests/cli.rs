use std::process::Command;

#[test]
fn config_check_does_not_make_service_ready() {
    let output = Command::new(env!("CARGO_BIN_EXE_radishlink-node"))
        .args([
            "check-config",
            concat!(env!("CARGO_MANIFEST_DIR"), "/config.example.json"),
        ])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(
        String::from_utf8(output.stdout)
            .unwrap()
            .contains("SECURITY_UNAVAILABLE")
    );
    let output = Command::new(env!("CARGO_BIN_EXE_radishlink-node"))
        .arg("run")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
}

#[test]
fn control_cli_reports_capabilities_without_opening_a_store() {
    let output = Command::new(env!("CARGO_BIN_EXE_radishlinkctl"))
        .arg("capabilities")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(
        String::from_utf8(output.stdout)
            .unwrap()
            .contains("ready=false")
    );
}
