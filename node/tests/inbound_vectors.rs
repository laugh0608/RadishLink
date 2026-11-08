//! Validate fixture construction and exact byte preservation through framing.
//! The expected decode verdicts are inputs for D14 candidate validation.
use radishlink_node::{
    framing::{Ingress, MAX_BODY_BYTES},
    model::Clock,
};
use serde::Deserialize;
use std::collections::{BTreeMap, BTreeSet};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Corpus {
    version: u8,
    base_bodies: BTreeMap<String, Vec<Part>>,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Part {
    Hex(String),
    Run { hex: String, repeat: usize },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    name: String,
    base: String,
    expect: Verdict,
    splice: Option<(usize, String, String)>,
    body_bytes: usize,
    #[serde(default)]
    preserve: BTreeMap<String, (usize, usize)>,
}

#[derive(Deserialize)]
#[serde(rename_all = "kebab-case")]
enum Verdict {
    DataShape,
    OuterCoseShape,
    ReceiptShape,
    ExitShape,
    ReportShape,
    DataAckShape,
    ControlAckShape,
    RejectEnvelope,
    RejectCore,
    RejectCoseProfile,
}

fn hex_bytes(hex: &str) -> Vec<u8> {
    assert_eq!(hex.len() % 2, 0);
    (0..hex.len())
        .step_by(2)
        .map(|start| u8::from_str_radix(&hex[start..start + 2], 16).unwrap())
        .collect()
}

fn body(parts: &[Part]) -> Vec<u8> {
    let mut body = Vec::new();
    for part in parts {
        match part {
            Part::Hex(hex) => body.extend(hex_bytes(hex)),
            Part::Run { hex, repeat } => {
                let bytes = hex_bytes(hex);
                assert!(!bytes.is_empty());
                assert!(*repeat <= (MAX_BODY_BYTES - body.len()) / bytes.len());
                body.extend(bytes.repeat(*repeat));
            }
        }
    }
    body
}

#[test]
fn inbound_wire_vectors_reconstruct_and_preserve_original_bytes() {
    let corpus: Corpus =
        serde_json::from_str(include_str!("fixtures/inbound-wire-v1.json")).unwrap();
    assert_eq!(corpus.version, 1);
    let mut names = BTreeSet::new();
    let clock = Clock {
        boot: "synthetic-vectors".into(),
        monotonic_ms: 0,
        trusted_utc: None,
    };
    let mut ingress = Ingress::new(&clock).unwrap();
    let neighbor = [7; 16];
    ingress.open(neighbor, &clock).unwrap();

    for case in &corpus.cases {
        assert!(names.insert(&case.name), "{}", case.name);
        let mut original = body(&corpus.base_bodies[&case.base]);
        if let Some((offset, old, new)) = &case.splice {
            let old = hex_bytes(old);
            let end = offset + old.len();
            assert_eq!(&original[*offset..end], old, "{}", case.name);
            original.splice(*offset..end, hex_bytes(new));
        }
        assert_eq!(original.len(), case.body_bytes, "{}", case.name);
        assert!((1..=MAX_BODY_BYTES).contains(&original.len()));
        let prefix = (original.len() as u32).to_be_bytes();
        let progress = ingress.push(&neighbor, &clock, &prefix).unwrap();
        assert_eq!(progress.consumed, prefix.len());
        assert!(!progress.complete);
        let mut remaining = original.len();
        for chunk in original.chunks(4096) {
            let progress = ingress.push(&neighbor, &clock, chunk).unwrap();
            assert_eq!(progress.consumed, chunk.len());
            remaining -= chunk.len();
            assert_eq!(progress.complete, remaining == 0);
        }
        let received = ingress.take(&neighbor, &clock).unwrap().unwrap();
        assert_eq!(received, original, "{}", case.name);
        let span = |name| {
            let (offset, len) = case.preserve[name];
            assert!(len > 0);
            &received[offset..offset + len]
        };
        match case.expect {
            Verdict::DataShape => {
                assert_eq!(&span("core")[..3], &[0x8f, 1, 1]);
                assert_eq!(span("core").len(), 216);
                assert_eq!(span("mls").len(), 61_440);
                assert_eq!(received.len(), 61_704);
            }
            Verdict::OuterCoseShape => {
                assert!(matches!(span("cose").len(), 1 | 512));
            }
            Verdict::ReceiptShape | Verdict::ExitShape | Verdict::ReportShape => {
                assert_eq!(&span("cose")[..2], &[0xd2, 0x84]);
                assert_eq!(&span("protected")[..3], &[0xa3, 1, 0x32]);
                let kind = match case.expect {
                    Verdict::ReceiptShape => 1,
                    Verdict::ExitShape => 2,
                    Verdict::ReportShape => 3,
                    _ => unreachable!(),
                };
                assert_eq!(&span("payload")[..3], &[0x89, 1, kind]);
            }
            Verdict::DataAckShape | Verdict::ControlAckShape => {
                assert_eq!(received.len(), 123);
                let kind = if matches!(case.expect, Verdict::DataAckShape) {
                    1
                } else {
                    2
                };
                assert_eq!(received[37], kind);
            }
            Verdict::RejectEnvelope | Verdict::RejectCore | Verdict::RejectCoseProfile => {
                assert!(case.preserve.is_empty());
            }
        }
    }
}
