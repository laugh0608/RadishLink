//! Bounded unverified control admission owned by Store. No network or verifier is enabled.
use super::*;
use std::{
    collections::{BTreeMap, VecDeque},
    sync::Arc,
};

pub const MAX_PENDING_CONTROLS: usize = 16;
const MAX_CONTROL_BYTES: usize = 512;

struct Bucket {
    last: i64,
    milli_tokens: i64,
}
impl Bucket {
    fn empty(now: i64) -> Self {
        Self {
            last: now,
            milli_tokens: 0,
        }
    }
    fn refill(&mut self, now: i64, rate: i64, burst: i64) -> Result<()> {
        if now < self.last {
            return Err(Error::new(
                Code::TimeUncertain,
                "control ingress rate clock",
            ));
        }
        let elapsed = (now - self.last).min(2000);
        self.milli_tokens = (self.milli_tokens + elapsed * rate).min(burst * 1000);
        self.last = now;
        Ok(())
    }
}
struct Pending {
    id: u64,
    activity: ActivityId,
    neighbor: CredentialRef,
    revision: i64,
    bytes: Arc<[u8]>,
    leased: bool,
}
/// Runtime-only. Reopening creates empty buckets at the current trusted coordinate.
/// The owner identity prevents a stale job from matching a reused local sequence number.
pub(super) struct ControlIngress {
    owner: Arc<()>,
    started: i64,
    global: Bucket,
    peers: BTreeMap<ParticipantId, Bucket>,
    next_id: u64,
    pending: VecDeque<Pending>,
}
impl ControlIngress {
    pub(super) fn new(now: i64) -> Self {
        Self {
            owner: Arc::new(()),
            started: now,
            global: Bucket::empty(now),
            peers: BTreeMap::new(),
            next_id: 0,
            pending: VecDeque::new(),
        }
    }
    fn charge(&mut self, participant: ParticipantId, now: i64) -> Result<bool> {
        if !self.peers.contains_key(&participant) && self.peers.len() == 4 {
            return Err(Error::new(Code::Quota, "control ingress peer slots"));
        }
        let peer = self
            .peers
            .entry(participant)
            .or_insert_with(|| Bucket::empty(self.started));
        self.global.refill(now, 4, 4)?;
        peer.refill(now, 1, 2)?;
        if self.global.milli_tokens < 1000 || peer.milli_tokens < 1000 {
            return Ok(false);
        }
        self.global.milli_tokens -= 1000;
        peer.milli_tokens -= 1000;
        Ok(true)
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ControlIngressAdmission {
    Queued,
    AlreadyPending,
    /// Exact persisted original bytes; no new custody, forwarding slot or ACK is implied.
    Known(ObjectRef),
    RateLimited,
    QueueFull,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ControlIngressUsage {
    pub waiting: usize,
    pub verifying: usize,
    /// Shared immutable object storage; jobs borrow the same allocation via Arc.
    pub object_bytes: usize,
    pub peer_buckets: usize,
}
/// Not Clone/Debug/serializable. A lease keeps its slot until completion/cancellation.
/// This job is neither an authenticated object nor a permission to persist its bytes.
pub struct ControlVerificationJob {
    owner: Arc<()>,
    id: u64,
    activity: ActivityId,
    neighbor: CredentialRef,
    revision: i64,
    bytes: Arc<[u8]>,
}
impl ControlVerificationJob {
    pub fn cose(&self) -> &[u8] {
        &self.bytes
    }
    pub fn activity(&self) -> ActivityId {
        self.activity
    }
    pub fn neighbor(&self) -> CredentialRef {
        self.neighbor
    }
    pub fn policy_revision(&self) -> i64 {
        self.revision
    }
}
pub struct ControlVerificationPoll {
    pub job: Option<ControlVerificationJob>,
    /// Explicit bounded refusals for waiting objects whose authorization/lifetime changed.
    pub discarded: Vec<Error>,
}
pub enum ControlVerificationOutcome {
    Rejected,
    /// Only a future approved strict decoder/verifier may supply this in production.
    Verified(Box<PreparedControl>),
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ControlVerificationCompletion {
    Rejected,
    Accepted(ControlAdmission),
}

impl Store {
    fn control_ingress_context(
        &self,
        activity: ActivityId,
        neighbor: CredentialRef,
    ) -> Result<(ParticipantId, i64)> {
        let local = self.control_live(&activity, self.clock.monotonic_ms)?;
        self.reject_local_retirement()?;
        if !self.participant_active(&local)? {
            return Err(Error::new(
                Code::Conflict,
                "control ingress local binding inactive",
            ));
        }
        let raw: Option<Vec<u8>> = self
            .conn
            .query_row(
                "SELECT participant FROM control_bindings WHERE credential=?1 AND state='active'",
                [neighbor.as_slice()],
                |r| r.get(0),
            )
            .optional()?;
        let peer: ParticipantId = raw
            .ok_or_else(|| Error::new(Code::Conflict, "control ingress neighbor inactive"))?
            .try_into()
            .map_err(|_| Error::new(Code::StoreCorrupt, "ingress participant size"))?;
        if peer == local {
            return Err(Error::new(Code::Conflict, "control ingress local channel"));
        }
        Ok((peer, self.business_policy_revision(activity)?))
    }
    /// Current Store clock must already be advanced by the trusted owner. Does not write SQL.
    /// Frame assembly and strict envelope routing are separate prerequisites; the supplied
    /// body is opaque COSE bytes, never parsed to trust a self-reported kind or priority.
    pub fn queue_control_candidate(
        &mut self,
        activity: ActivityId,
        neighbor: CredentialRef,
        bytes: &[u8],
    ) -> Result<ControlIngressAdmission> {
        let (peer, revision) = self.control_ingress_context(activity, neighbor)?;
        if bytes.is_empty() || bytes.len() > MAX_CONTROL_BYTES {
            return Err(Error::new(
                Code::InvalidInput,
                "control ingress object size",
            ));
        }
        if !self.ingress.charge(peer, self.clock.monotonic_ms)? {
            return Ok(ControlIngressAdmission::RateLimited);
        }
        // The bounded saved object set is the only verified-byte cache; claimed object refs
        // and hashes from unverified input are never used to skip verification.
        let known:Option<(Vec<u8>,bool)>=self.conn.query_row("SELECT o.reference,(o.kind=2 OR b.state='active') FROM control_objects o JOIN control_bindings b ON b.credential=o.issuer WHERE o.body=?1",[bytes],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
        if let Some((reference, allowed)) = known {
            if !allowed {
                return Err(Error::new(Code::Conflict, "known control issuer inactive"));
            }
            return Ok(ControlIngressAdmission::Known(
                reference
                    .try_into()
                    .map_err(|_| Error::new(Code::StoreCorrupt, "known control reference"))?,
            ));
        }
        if self.ingress.pending.iter().any(|p| {
            p.activity == activity
                && p.neighbor == neighbor
                && p.revision == revision
                && p.bytes.as_ref() == bytes
        }) {
            return Ok(ControlIngressAdmission::AlreadyPending);
        }
        if self.ingress.pending.len() == MAX_PENDING_CONTROLS {
            return Ok(ControlIngressAdmission::QueueFull);
        }
        let id = self
            .ingress
            .next_id
            .checked_add(1)
            .ok_or_else(|| Error::new(Code::Quota, "control ingress ticket exhausted"))?;
        self.ingress.next_id = id;
        self.ingress.pending.push_back(Pending {
            id,
            activity,
            neighbor,
            revision,
            bytes: Arc::from(bytes),
            leased: false,
        });
        Ok(ControlIngressAdmission::Queued)
    }
    /// FIFO only after current authorization checks. Unverified bytes cannot claim exit priority.
    /// Removing a waiting stale item never replenishes rate tokens. Leased stale items still
    /// occupy slots until their worker returns/cancels, preventing unbounded in-flight jobs.
    pub fn next_control_verification(&mut self) -> Result<ControlVerificationPoll> {
        self.writable()?;
        let mut discarded = Vec::new();
        while let Some(index) = self.ingress.pending.iter().position(|p| !p.leased) {
            let pending = &self.ingress.pending[index];
            let context = self.control_ingress_context(pending.activity, pending.neighbor);
            let refusal = match context {
                Ok((_, revision)) if revision == pending.revision => None,
                Ok(_) => Some(Error::new(Code::Conflict, "queued control policy changed")),
                Err(e) if matches!(e.code, Code::Conflict | Code::Expired) => Some(e),
                Err(e) => return Err(e),
            };
            if let Some(refusal) = refusal {
                self.ingress.pending.remove(index);
                discarded.push(refusal);
                continue;
            }
            let pending = &mut self.ingress.pending[index];
            pending.leased = true;
            return Ok(ControlVerificationPoll {
                discarded,
                job: Some(ControlVerificationJob {
                    owner: self.ingress.owner.clone(),
                    id: pending.id,
                    activity: pending.activity,
                    neighbor: pending.neighbor,
                    revision: pending.revision,
                    bytes: pending.bytes.clone(),
                }),
            });
        }
        Ok(ControlVerificationPoll {
            discarded,
            job: None,
        })
    }
    fn release_control_job(&mut self, job: &ControlVerificationJob) -> Result<Pending> {
        if !Arc::ptr_eq(&job.owner, &self.ingress.owner) {
            return Err(Error::new(
                Code::Conflict,
                "control verification owner changed",
            ));
        }
        let index = self
            .ingress
            .pending
            .iter()
            .position(|p| p.id == job.id && p.leased)
            .ok_or_else(|| Error::new(Code::Conflict, "control verification job missing"))?;
        Ok(self
            .ingress
            .pending
            .remove(index)
            .expect("located verification slot"))
    }
    /// Cancellation releases a lease only; callers must stop/join the corresponding worker.
    pub fn cancel_control_verification(&mut self, job: ControlVerificationJob) -> Result<()> {
        self.release_control_job(&job)?;
        Ok(())
    }
    /// A failed/rejected result releases its slot without refunding tokens or creating an ACK.
    /// Exact wire bytes, activity, channel and captured policy are rechecked before the
    /// existing atomic control acceptance. No verifier, parser or transport is called here.
    pub fn complete_control_verification(
        &mut self,
        job: ControlVerificationJob,
        outcome: ControlVerificationOutcome,
        neighbors: &[ControlNeighbor],
    ) -> Result<ControlVerificationCompletion> {
        let pending = self.release_control_job(&job)?;
        if matches!(outcome, ControlVerificationOutcome::Rejected) {
            return Ok(ControlVerificationCompletion::Rejected);
        }
        let ControlVerificationOutcome::Verified(object) = outcome else {
            unreachable!()
        };
        if object.cose.as_slice() != pending.bytes.as_ref()
            || object.fields.activity != pending.activity
        {
            return Err(Error::new(
                Code::Conflict,
                "verified control differs from queued object",
            ));
        }
        let admission = self.policy_atomic(|s| {
            let (_, revision) = s.control_ingress_context(pending.activity, pending.neighbor)?;
            if revision != pending.revision {
                return Err(Error::new(
                    Code::Conflict,
                    "control verification policy changed",
                ));
            }
            s.accept_control_in_transaction(&object, neighbors)
        })?;
        Ok(ControlVerificationCompletion::Accepted(admission))
    }
    /// Bounded metadata only; never exposes queued bytes, credentials or decoded payloads.
    pub fn control_ingress_usage(&self) -> ControlIngressUsage {
        let verifying = self.ingress.pending.iter().filter(|p| p.leased).count();
        ControlIngressUsage {
            waiting: self.ingress.pending.len() - verifying,
            verifying,
            object_bytes: self.ingress.pending.iter().map(|p| p.bytes.len()).sum(),
            peer_buckets: self.ingress.peers.len(),
        }
    }
}
