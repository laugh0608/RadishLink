//! Bounded discovery of retained responsibilities, never readiness or output permission.
use super::*;
use std::sync::Arc;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OutboundLane {
    Exit,
    OrdinaryControl,
    Data,
}

/// Facts only. Link, retry time, admission, policy and final handoff still need checking.
/// ACK requests originate in verified input and are deliberately not synthesized here.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OutboundCandidate {
    Queue(QueueKey),
    Control {
        object: ObjectRef,
        neighbor: ParticipantId,
    },
}

/// Opaque, runtime-only position. Not transferable across owners, activities or clock domains.
/// Dropping it does not consume a responsibility, retry, token or persistent rotation cursor.
pub struct OutboundScan {
    owner: Arc<()>,
    domain: ClockDomainId,
    activity: ActivityId,
    lane: OutboundLane,
    last: Option<OutboundCandidate>,
    complete: bool,
}

pub struct OutboundPage {
    pub domain: ClockDomainId,
    pub activity: ActivityId,
    /// Revision at discovery, not a grant to act on an old snapshot.
    pub revision: i64,
    pub lane: OutboundLane,
    /// At most the existing 128-event batch ceiling; no bodies or prepared events.
    pub candidates: Vec<OutboundCandidate>,
    pub complete: bool,
}

impl Store {
    pub fn start_outbound_scan(&self, lane: OutboundLane) -> Result<OutboundScan> {
        let activity = self.current_activity_id()?;
        self.control_live(&activity, self.clock.monotonic_ms)?;
        Ok(OutboundScan {
            owner: self.ingress.owner().clone(),
            domain: self.current_domain_id()?,
            activity,
            lane,
            last: None,
            complete: false,
        })
    }

    /// Stable keyset traversal, without OFFSET or loading all retained responsibilities.
    /// Changes behind the position wait for a new scan; this is not a frozen ready set.
    /// Read errors leave the position untouched. A finished scan must be explicitly replaced.
    pub fn scan_outbound_page(&self, scan: &mut OutboundScan) -> Result<OutboundPage> {
        self.writable()?;
        if !Arc::ptr_eq(&scan.owner, self.ingress.owner())
            || scan.domain != self.current_domain_id()?
            || scan.activity != self.current_activity_id()?
            || scan.complete
        {
            return Err(Error::new(
                Code::Conflict,
                "outbound scan scope or completion",
            ));
        }
        self.control_live(&scan.activity, self.clock.monotonic_ms)?;
        let revision = self.revision()?;
        let mut candidates = Vec::new();
        match scan.lane {
            OutboundLane::Data => {
                self.scan_queues(scan, QueueKind::Data, &mut candidates)?;
            }
            OutboundLane::Exit => {
                self.scan_controls(scan, ControlKind::Exit, &mut candidates)?;
            }
            OutboundLane::OrdinaryControl => {
                if !matches!(scan.last, Some(OutboundCandidate::Control { .. })) {
                    self.scan_queues(scan, QueueKind::Evidence, &mut candidates)?;
                }
                if candidates.len() <= scheduling::MAX_QUEUE_EVENTS {
                    self.scan_controls(scan, ControlKind::Report, &mut candidates)?;
                }
            }
        }
        let complete = candidates.len() <= scheduling::MAX_QUEUE_EVENTS;
        if !complete {
            candidates.pop(); // one lookahead key, not another returned event
        }
        if let Some(last) = candidates.last() {
            scan.last = Some(last.clone());
        }
        scan.complete = complete;
        Ok(OutboundPage {
            domain: scan.domain,
            activity: scan.activity,
            revision,
            lane: scan.lane,
            candidates,
            complete,
        })
    }

    fn scan_queues(
        &self,
        scan: &OutboundScan,
        kind: QueueKind,
        candidates: &mut Vec<OutboundCandidate>,
    ) -> Result<()> {
        let (message, neighbor) = match &scan.last {
            Some(OutboundCandidate::Queue(q)) => (q.message.as_str(), q.neighbor.as_str()),
            _ => ("", ""),
        };
        let mut statement = self.conn.prepare(
            "SELECT q.message_key,q.neighbor FROM queues q
             JOIN messages m ON m.key=q.message_key JOIN message_data d ON d.message_key=m.key
             WHERE q.kind=?1 AND m.domain_id=?2 AND d.activity_id=?3 AND m.policy_stopped=0
             AND (q.message_key,q.neighbor)>(?4,?5)
             ORDER BY q.message_key,q.neighbor LIMIT ?6",
        )?;
        let mut rows = statement.query(params![
            kind.as_str(),
            scan.domain.as_slice(),
            scan.activity.as_slice(),
            message,
            neighbor,
            (scheduling::MAX_QUEUE_EVENTS + 1 - candidates.len()) as i64
        ])?;
        while let Some(row) = rows.next()? {
            let message: String = row.get(0)?;
            let neighbor: String = row.get(1)?;
            for value in [&message, &neighbor] {
                check_ref(value).map_err(|e| {
                    Error::source_error(Code::StoreCorrupt, "outbound scan queue key", e)
                })?;
            }
            candidates.push(OutboundCandidate::Queue(QueueKey {
                message,
                neighbor,
                kind,
            }));
        }
        Ok(())
    }

    fn scan_controls(
        &self,
        scan: &OutboundScan,
        kind: ControlKind,
        candidates: &mut Vec<OutboundCandidate>,
    ) -> Result<()> {
        // Empty BLOB sorts before every valid 32/16-byte identifier, including all-zero IDs.
        let (object, neighbor): (&[u8], &[u8]) = match &scan.last {
            Some(OutboundCandidate::Control { object, neighbor }) => (object, neighbor),
            _ => (&[], &[]),
        };
        let mut statement = self.conn.prepare(
            "SELECT n.object,n.participant FROM control_neighbors n
             JOIN control_objects o ON o.reference=n.object
             WHERE n.activity=?1 AND o.kind=?2 AND n.terminal=0
             AND (n.object,n.participant)>(?3,?4)
             ORDER BY n.object,n.participant LIMIT ?5",
        )?;
        let mut rows = statement.query(params![
            scan.activity.as_slice(),
            kind.number(),
            object,
            neighbor,
            (scheduling::MAX_QUEUE_EVENTS + 1 - candidates.len()) as i64
        ])?;
        while let Some(row) = rows.next()? {
            let object: Vec<u8> = row.get(0)?;
            let neighbor: Vec<u8> = row.get(1)?;
            candidates.push(OutboundCandidate::Control {
                object: object
                    .try_into()
                    .map_err(|_| Error::new(Code::StoreCorrupt, "outbound scan object size"))?,
                neighbor: neighbor
                    .try_into()
                    .map_err(|_| Error::new(Code::StoreCorrupt, "outbound scan neighbor size"))?,
            });
        }
        Ok(())
    }
}
