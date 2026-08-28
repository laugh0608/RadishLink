use serde::Serialize;

#[derive(Debug, Serialize)]
pub struct PhaseGateEvidence<'a> {
    pub schema_version: u8,
    pub evidence_id: &'a str,
    pub phase: &'a str,
    pub command: &'a str,
    pub outcome: &'a str,
    pub reason: &'a str,
}

impl<'a> PhaseGateEvidence<'a> {
    pub fn blocked(command: &'a str) -> Self {
        Self {
            schema_version: 1,
            evidence_id: "SW-EXP-002",
            phase: "phase-b",
            command,
            outcome: "BLOCKED",
            reason: "Phase B has not been authorized or implemented",
        }
    }
}

pub fn print_json<T: Serialize>(value: &T) -> Result<(), String> {
    let encoded = serde_json::to_string(value)
        .map_err(|error| format!("could not serialize evidence: {error}"))?;
    println!("{encoded}");
    Ok(())
}
