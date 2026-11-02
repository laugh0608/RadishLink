//! One synchronous trusted-owner scheduling step. No verifier, transport or worker is started.
use super::*;

// D16: at most 20 retained exits, each with at most 4 neighbor responsibilities.
const MAX_CYCLE_EXITS: usize = 20 * 4;
const LANE_WORK: usize = (scheduling::MAX_QUEUE_EVENTS - MAX_CYCLE_EXITS) / 3;
pub const MAX_CYCLE_ACKS: usize = LANE_WORK;
const _: () = assert!(MAX_CYCLE_EXITS + 3 * LANE_WORK <= scheduling::MAX_QUEUE_EVENTS);

/// Caller-verified input, never derived from a scan or an unverified claimed object ID.
pub enum OutboundAck {
    Data {
        message: String,
        neighbor: String,
    },
    Control {
        object: ObjectRef,
        neighbor: ParticipantId,
    },
}

/// Owned cutoff: caller has already applied local controls and complete verified results,
/// merged all same-coordinate observations, and captured this revision and trusted Clock.
pub struct OutboundCycleInput {
    pub clock: Clock,
    pub expected_revision: i64,
    pub acknowledgements: Vec<OutboundAck>,
}

/// One owner's runtime traversal positions. Reopening does not restore old input or decisions.
/// Not Clone/Debug/serializable; use one handle in the existing serial state owner.
pub struct OutboundCycle {
    data: OutboundScan,
    ordinary: OutboundScan,
    last_ms: Option<i64>,
}

pub struct OutboundCycleReport {
    /// Existing committed decisions only, never reusable or final I/O permissions.
    pub outbound: OutboundReport,
    pub cutoff_revision: i64,
    pub exit_candidates: usize,
    pub data_candidates: usize,
    pub ordinary_candidates: usize,
    pub ack_inputs: usize,
    pub data_complete: bool,
    pub ordinary_complete: bool,
}

impl Store {
    pub fn start_outbound_cycle(&self) -> Result<OutboundCycle> {
        Ok(OutboundCycle {
            data: self.start_outbound_scan(OutboundLane::Data)?,
            ordinary: self.start_outbound_scan(OutboundLane::OrdinaryControl)?,
            last_ms: None,
        })
    }

    /// At most 80 exit + 16 ordinary + 16 data + 16 explicit ACK events, in one old transaction.
    /// `observe` only reads the caller's already captured, authenticated, merged input. It must
    /// be bounded/nonblocking and cause no external effects; it cannot mutate this borrowed Store.
    /// Late input waits for a later trusted millisecond. No fallback observation is invented.
    pub fn process_outbound_cycle(
        &mut self,
        cycle: &mut OutboundCycle,
        input: OutboundCycleInput,
        mut observe: impl FnMut(&OutboundCandidate) -> Result<Batch>,
    ) -> Result<OutboundCycleReport> {
        self.validate_clock_advance(&input.clock)?;
        cycle.data.check_scope(self)?;
        cycle.ordinary.check_scope(self)?;
        if self.revision()? != input.expected_revision {
            return Err(Error::new(Code::Conflict, "outbound cycle cutoff revision"));
        }
        if cycle
            .last_ms
            .is_some_and(|last| input.clock.monotonic_ms <= last)
        {
            return Err(Error::new(
                Code::Conflict,
                "outbound cycle coordinate already closed",
            ));
        }
        if input.acknowledgements.len() > MAX_CYCLE_ACKS {
            return Err(Error::new(
                Code::InvalidInput,
                "outbound cycle ACK input limit",
            ));
        }
        let activity = self.current_activity_id()?;
        self.control_live(&activity, input.clock.monotonic_ms)?;

        let mut exits = self.start_outbound_scan(OutboundLane::Exit)?;
        let exits = self.scan_outbound_limit(&mut exits, MAX_CYCLE_EXITS)?;
        if !exits.complete {
            return Err(Error::new(
                Code::StoreCorrupt,
                "outbound exit set exceeds D16 bound",
            ));
        }
        let mut data = if cycle.data.complete() {
            self.start_outbound_scan(OutboundLane::Data)?
        } else {
            cycle.data.staged()
        };
        let mut ordinary = if cycle.ordinary.complete() {
            self.start_outbound_scan(OutboundLane::OrdinaryControl)?
        } else {
            cycle.ordinary.staged()
        };
        let data_page = self.scan_outbound_limit(&mut data, LANE_WORK)?;
        let ordinary_page = self.scan_outbound_limit(&mut ordinary, LANE_WORK)?;
        let exit_candidates = exits.candidates.len();
        let data_candidates = data_page.candidates.len();
        let ordinary_candidates = ordinary_page.candidates.len();
        let ack_inputs = input.acknowledgements.len();
        let data_complete = data_page.complete;
        let ordinary_complete = ordinary_page.complete;
        let mut events = Vec::new();
        for candidate in exits
            .candidates
            .into_iter()
            .chain(ordinary_page.candidates)
            .chain(data_page.candidates)
        {
            let batch = observe(&candidate)?;
            if batch.now_ms != input.clock.monotonic_ms {
                return Err(Error::new(
                    Code::InvalidInput,
                    "outbound cycle observation coordinate",
                ));
            }
            events.push(match candidate {
                OutboundCandidate::Queue(queue) => {
                    OutboundEvent::Queue(QueueEvent { queue, batch })
                }
                OutboundCandidate::Control { object, neighbor } => {
                    OutboundEvent::Control(ControlEvent {
                        object,
                        neighbor,
                        link: batch.link,
                        signal: batch.signal,
                        admission: batch.admission,
                    })
                }
            });
        }
        for ack in input.acknowledgements {
            events.push(match ack {
                OutboundAck::Data { message, neighbor } => {
                    OutboundEvent::DataAck { message, neighbor }
                }
                OutboundAck::Control { object, neighbor } => {
                    OutboundEvent::ControlAck { object, neighbor }
                }
            });
        }
        let now = input.clock.monotonic_ms;
        let outbound = if events.is_empty() {
            OutboundReport {
                decisions: Vec::new(),
                maintenance: self.maintain(input.clock)?,
            }
        } else {
            self.process_outbound_batch(input.clock, events)?
        };
        // No fallible work after the successful COMMIT. An Err never publishes these positions.
        cycle.data = data;
        cycle.ordinary = ordinary;
        cycle.last_ms = Some(now);
        Ok(OutboundCycleReport {
            outbound,
            cutoff_revision: input.expected_revision,
            exit_candidates,
            data_candidates,
            ordinary_candidates,
            ack_inputs,
            data_complete,
            ordinary_complete,
        })
    }
}
