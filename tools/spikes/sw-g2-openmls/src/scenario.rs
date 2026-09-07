use crate::evidence::{print_json, PhaseGateEvidence};

pub const PHASE_B_COMMANDS: &[&str] = &[
    "init",
    "key-package",
    "create-group",
    "join",
    "encrypt",
    "decrypt",
    "process-commit",
    "inspect",
];

pub fn reject_until_phase_b(command: &str) -> Result<(), String> {
    print_json(&PhaseGateEvidence::blocked(command))?;
    Err(format!(
        "Phase B command '{command}' is blocked pending separate authorization"
    ))
}

pub fn is_phase_b_command(command: &str) -> bool {
    PHASE_B_COMMANDS.contains(&command)
}

#[cfg(test)]
mod tests {
    use super::{is_phase_b_command, PHASE_B_COMMANDS};

    #[test]
    fn every_declared_phase_b_command_is_recognized() {
        for command in PHASE_B_COMMANDS {
            assert!(is_phase_b_command(command));
        }
    }

    #[test]
    fn preparation_command_is_not_a_phase_b_command() {
        assert!(!is_phase_b_command("phase-a-info"));
    }
}
