mod evidence;
mod scenario;
mod store;

use serde::Serialize;

use crate::evidence::print_json;

#[derive(Serialize)]
struct PhaseAInfo<'a> {
    schema_version: u8,
    evidence_id: &'a str,
    phase: &'a str,
    candidate: &'a str,
    status: &'a str,
    phase_b_commands: &'a [&'a str],
}

fn usage() -> String {
    format!(
        "usage: radishlink-sw-g2-openmls-spike <phase-a-info|{}>",
        scenario::PHASE_B_COMMANDS.join("|")
    )
}

fn run() -> Result<(), String> {
    let mut arguments = std::env::args();
    let _program = arguments.next();
    let command = arguments.next().ok_or_else(usage)?;

    if arguments.next().is_some() {
        return Err(format!("unexpected extra arguments; {}", usage()));
    }

    if command == "phase-a-info" {
        let info = PhaseAInfo {
            schema_version: 1,
            evidence_id: "SW-EXP-002",
            phase: "phase-a",
            candidate: "OpenMLS 0.8.1",
            status: "dependency-audit-only",
            phase_b_commands: scenario::PHASE_B_COMMANDS,
        };
        return print_json(&info);
    }

    if scenario::is_phase_b_command(&command) {
        return scenario::reject_until_phase_b(&command);
    }

    Err(format!("unknown command '{command}'; {}", usage()))
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use crate::store::validate_relative_artifact_path;

    #[test]
    fn evidence_paths_remain_relative() {
        assert!(validate_relative_artifact_path(Path::new("evidence/summary.json")).is_ok());
    }
}
