//! Bounded unverified control admission owned by Store. No network or verifier is enabled.
use super::*;
use std::{
    collections::{BTreeMap, VecDeque},
    sync::Arc,
};

mod read;
pub use read::{
    DecodedInbound, InboundDispatch, InboundFrame, InboundPayload, InboundPayloadCredit,
    InboundReadProgress, InboundReadStep,
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
#[derive(Clone, Copy, PartialEq, Eq)]
enum ControlSource {
    Credential(CredentialRef),
    Channel(OutboundChannel),
}
impl ControlSource {
    fn neighbor(self) -> CredentialRef {
        match self {
            Self::Credential(neighbor) => neighbor,
            Self::Channel(channel) => channel.peer_credential,
        }
    }
}

struct Pending {
    id: u64,
    activity: ActivityId,
    domain: ClockDomainId,
    source: ControlSource,
    revision: i64,
    bytes: Arc<[u8]>,
    leased: bool,
}

struct RegisteredChannel {
    binding: OutboundChannel,
    closing: bool,
    /// None until the frame slot is open, then one coalesced readiness bit.
    read_ready: Option<bool>,
}

/// Runtime-only. Reopening creates empty buckets at the current trusted coordinate.
/// The owner identity prevents a stale job from matching a reused local sequence number.
pub(super) struct ControlIngress {
    owner: Arc<()>,
    started: i64,
    global: Bucket,
    peers: BTreeMap<ParticipantId, Bucket>,
    channels: BTreeMap<ParticipantId, RegisteredChannel>,
    framing: Option<crate::framing::Ingress>,
    last_read_peer: Option<ParticipantId>,
    next_instance: u64,
    next_id: u64,
    pending: VecDeque<Pending>,
}
impl ControlIngress {
    pub(super) fn owner(&self) -> &Arc<()> {
        &self.owner
    }
    pub(super) fn new(now: i64) -> Self {
        Self {
            owner: Arc::new(()),
            started: now,
            global: Bucket::empty(now),
            peers: BTreeMap::new(),
            channels: BTreeMap::new(),
            framing: None,
            last_read_peer: None,
            next_instance: OutboundChannel::REGISTERED_INSTANCE_START,
            next_id: 0,
            pending: VecDeque::new(),
        }
    }
    pub(super) fn has_channels(&self) -> bool {
        !self.channels.is_empty()
    }
    pub(super) fn registered_channels(&self) -> impl Iterator<Item = OutboundChannel> + '_ {
        self.channels.values().map(|entry| entry.binding)
    }
    pub(super) fn discard_waiting(&mut self) {
        self.pending.retain(|pending| pending.leased);
    }
    pub(super) fn require_channel(&self, channel: &OutboundChannel) -> Result<()> {
        match self.channels.get(&channel.peer) {
            Some(entry) if entry.binding == *channel && !entry.closing => Ok(()),
            Some(entry) if entry.binding == *channel => Err(Error::new(
                Code::Conflict,
                "control ingress channel closing",
            )),
            _ => Err(Error::new(
                Code::Conflict,
                "control ingress channel instance changed",
            )),
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
/// Runtime handle allocated by the Store after the caller supplies authenticated bindings.
/// The handle records that instance; it performs no transport authentication itself.
pub struct ControlIngressChannel {
    owner: Arc<()>,
    activity: ActivityId,
    binding: OutboundChannel,
}
impl ControlIngressChannel {
    pub fn binding(&self) -> OutboundChannel {
        self.binding
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ControlIngressAdmission {
    Queued,
    AlreadyPending,
    /// Exact persisted original bytes. The channel API reports ACK admission separately.
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
    domain: ClockDomainId,
    source: ControlSource,
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
        self.source.neighbor()
    }
    pub fn channel(&self) -> Option<OutboundChannel> {
        match self.source {
            ControlSource::Credential(_) => None,
            ControlSource::Channel(channel) => Some(channel),
        }
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

struct IngressContext {
    local: ParticipantId,
    peer: ParticipantId,
    policy_revision: i64,
}

impl Store {
    fn control_ingress_context(
        &self,
        activity: ActivityId,
        source: ControlSource,
    ) -> Result<IngressContext> {
        let local = self.control_live(&activity, self.clock.monotonic_ms)?;
        self.reject_local_retirement()?;
        let peer = match source {
            ControlSource::Credential(neighbor) => self.control_ingress_peer(&local, &neighbor)?,
            ControlSource::Channel(channel) => {
                self.ingress.require_channel(&channel)?;
                if local != channel.local
                    || self.control_binding(&channel.local_credential, &local)?
                        != BindingState::Active
                    || self.control_binding(&channel.peer_credential, &channel.peer)?
                        != BindingState::Active
                {
                    return Err(Error::new(
                        Code::Conflict,
                        "control ingress channel binding inactive",
                    ));
                }
                channel.peer
            }
        };
        if peer == local {
            return Err(Error::new(Code::Conflict, "control ingress local channel"));
        }
        Ok(IngressContext {
            local,
            peer,
            policy_revision: self.business_policy_revision(activity)?,
        })
    }

    fn control_ingress_peer(
        &self,
        local: &ParticipantId,
        neighbor: &CredentialRef,
    ) -> Result<ParticipantId> {
        if !self.participant_active(local)? {
            return Err(Error::new(
                Code::Conflict,
                "control ingress local binding inactive",
            ));
        }
        let raw: Option<Vec<u8>> = self
            .conn
            .query_row(
                "SELECT participant FROM current_control_bindings WHERE credential=?1 AND state='active'",
                [neighbor.as_slice()],
                |r| r.get(0),
            )
            .optional()?;
        raw.ok_or_else(|| Error::new(Code::Conflict, "control ingress neighbor inactive"))?
            .try_into()
            .map_err(|_| Error::new(Code::StoreCorrupt, "ingress participant size"))
    }

    /// Registers a new instance from caller-authenticated endpoints. Close the old
    /// instance before reconnecting, even when both credentials are unchanged.
    pub fn register_control_ingress_channel(
        &mut self,
        activity: ActivityId,
        local_credential: CredentialRef,
        neighbor: CredentialRef,
    ) -> Result<ControlIngressChannel> {
        let IngressContext { local, peer, .. } =
            self.control_ingress_context(activity, ControlSource::Credential(neighbor))?;
        if self.control_binding(&local_credential, &local)? != BindingState::Active {
            return Err(Error::new(
                Code::Conflict,
                "control ingress local channel credential inactive",
            ));
        }
        if self.ingress.channels.contains_key(&peer) {
            return Err(Error::new(
                Code::Conflict,
                "control ingress peer already registered",
            ));
        }
        if self.ingress.channels.len() >= crate::framing::MAX_NEIGHBORS {
            return Err(Error::new(Code::Quota, "control ingress channel count"));
        }
        let instance =
            self.ingress.next_instance.checked_add(1).ok_or_else(|| {
                Error::new(Code::Quota, "control ingress channel instance exhausted")
            })?;
        let binding = OutboundChannel {
            instance,
            local,
            local_credential,
            peer,
            peer_credential: neighbor,
        };
        self.ingress.channels.insert(
            peer,
            RegisteredChannel {
                binding,
                closing: false,
                read_ready: None,
            },
        );
        self.ingress.next_instance = instance;
        Ok(ControlIngressChannel {
            owner: self.ingress.owner.clone(),
            activity,
            binding,
        })
    }

    /// Fences this exact instance before the owner closes its transport. The registration
    /// still occupies its slot, and a worker must return or cancel each existing lease.
    pub fn begin_control_ingress_channel_close(
        &mut self,
        channel: &ControlIngressChannel,
    ) -> Result<()> {
        self.registered_control_channel(channel)?;
        self.fence_control_channel(channel.binding);
        Ok(())
    }

    fn fence_control_channel(&mut self, channel: OutboundChannel) {
        let entry = self
            .ingress
            .channels
            .get_mut(&channel.peer)
            .filter(|entry| entry.binding == channel)
            .expect("registered channel");
        entry.closing = true;
        entry.read_ready = None;
        if let Some(framing) = &mut self.ingress.framing {
            framing.close(&channel.peer);
        }
        self.discard_acks_on_channel(&channel);
        self.discard_handoff_on_channel(&channel);
    }

    /// Records confirmed closure of this exact instance. The caller owns transport closure.
    /// An already closed transport may be confirmed directly, including during owner shutdown.
    pub fn close_control_ingress_channel(&mut self, channel: &ControlIngressChannel) -> Result<()> {
        self.registered_control_channel(channel)?;
        self.ingress.channels.remove(&channel.binding.peer);
        if let Some(framing) = &mut self.ingress.framing {
            framing.close(&channel.binding.peer);
        }
        self.discard_acks_on_channel(&channel.binding);
        self.note_owner_channel_closed(channel.binding);
        Ok(())
    }

    fn registered_control_channel(
        &mut self,
        channel: &ControlIngressChannel,
    ) -> Result<&mut RegisteredChannel> {
        self.require_control_channel_owner(&channel.owner)?;
        self.ingress
            .channels
            .get_mut(&channel.binding.peer)
            .filter(|entry| entry.binding == channel.binding)
            .ok_or_else(|| Error::new(Code::Conflict, "control ingress channel instance changed"))
    }

    pub(super) fn control_ingress_channel(
        &self,
        channel: &ControlIngressChannel,
    ) -> Result<(ActivityId, OutboundChannel)> {
        self.require_control_channel_owner(&channel.owner)?;
        self.ingress.require_channel(&channel.binding)?;
        Ok((channel.activity, channel.binding))
    }

    pub(super) fn check_registered_channel(
        &self,
        activity: ActivityId,
        channel: &OutboundChannel,
        now: i64,
    ) -> Result<()> {
        self.ingress.require_channel(channel)?;
        let local = self.control_live(&activity, now)?;
        self.reject_local_retirement()?;
        if local != channel.local
            || self.control_binding(&channel.local_credential, &local)? != BindingState::Active
            || self.control_binding(&channel.peer_credential, &channel.peer)?
                != BindingState::Active
        {
            return Err(Error::new(
                Code::Conflict,
                "registered channel binding changed",
            ));
        }
        Ok(())
    }

    fn require_control_channel_owner(&self, owner: &Arc<()>) -> Result<()> {
        if !Arc::ptr_eq(owner, &self.ingress.owner) {
            return Err(Error::new(
                Code::Conflict,
                "control ingress channel owner changed",
            ));
        }
        Ok(())
    }

    pub(super) fn discard_inbound_reads(&mut self) {
        self.ingress.framing = None;
        for entry in self.ingress.channels.values_mut() {
            entry.read_ready = None;
        }
    }

    /// Admits candidate bytes with their exact source instance, in the original shared queue.
    pub fn queue_control_candidate_on_channel(
        &mut self,
        channel: &ControlIngressChannel,
        bytes: &[u8],
    ) -> Result<(ControlIngressAdmission, OutboundAckAdmission)> {
        self.require_control_channel_owner(&channel.owner)?;
        self.queue_control_source(
            channel.activity,
            ControlSource::Channel(channel.binding),
            bytes,
        )
    }

    /// Credential-only preparation for existing internal callers. A channel input uses
    /// `queue_control_candidate_on_channel`. Current Store clock must already be advanced.
    /// Frame assembly and strict envelope routing are separate prerequisites; the supplied
    /// body is opaque COSE bytes, never parsed to trust a self-reported kind or priority.
    pub fn queue_control_candidate(
        &mut self,
        activity: ActivityId,
        neighbor: CredentialRef,
        bytes: &[u8],
    ) -> Result<ControlIngressAdmission> {
        self.queue_control_source(activity, ControlSource::Credential(neighbor), bytes)
            .map(|(admission, _)| admission)
    }

    fn queue_control_source(
        &mut self,
        activity: ActivityId,
        source: ControlSource,
        bytes: &[u8],
    ) -> Result<(ControlIngressAdmission, OutboundAckAdmission)> {
        let IngressContext {
            peer,
            policy_revision: revision,
            ..
        } = self.control_ingress_context(activity, source)?;
        if bytes.is_empty() || bytes.len() > MAX_CONTROL_BYTES {
            return Err(Error::new(
                Code::InvalidInput,
                "control ingress object size",
            ));
        }
        if !self.ingress.charge(peer, self.clock.monotonic_ms)? {
            return Ok((
                ControlIngressAdmission::RateLimited,
                OutboundAckAdmission::NotEligible,
            ));
        }
        // The bounded saved object set is the only verified-byte cache; claimed object refs
        // and hashes from unverified input are never used to skip verification.
        let known: Option<(Vec<u8>, bool)> = {
            let mut stmt = self.conn.prepare(
                "SELECT o.reference,(o.kind=2 OR b.state='active')
                 FROM current_control_objects o JOIN current_control_bindings b ON b.credential=o.issuer
                 WHERE o.body=?1 LIMIT 2",
            )?;
            let mut rows = stmt.query([bytes])?;
            let first = rows
                .next()?
                .map(|row| Ok::<_, rusqlite::Error>((row.get(0)?, row.get(1)?)))
                .transpose()?;
            if rows.next()?.is_some() {
                return Err(Error::new(Code::Conflict, "ambiguous known control bytes"));
            }
            first
        };
        if let Some((reference, allowed)) = known {
            if !allowed {
                return Err(Error::new(Code::Conflict, "known control issuer inactive"));
            }
            let reference = reference
                .try_into()
                .map_err(|_| Error::new(Code::StoreCorrupt, "known control reference"))?;
            let ack = if let ControlSource::Channel(channel) = source
                && self
                    .registered_control_ack_progress(
                        activity,
                        &channel,
                        reference,
                        self.clock.monotonic_ms,
                    )?
                    .is_some_and(|progress| progress.ack_attempts < 10)
            {
                self.queue_committed_ack(
                    activity,
                    channel,
                    outbound_ack::AckTarget::Control(reference),
                )
            } else {
                OutboundAckAdmission::NotEligible
            };
            return Ok((ControlIngressAdmission::Known(reference), ack));
        }
        if self.ingress.pending.iter().any(|p| {
            p.activity == activity
                && p.source == source
                && p.revision == revision
                && p.bytes.as_ref() == bytes
        }) {
            return Ok((
                ControlIngressAdmission::AlreadyPending,
                OutboundAckAdmission::NotEligible,
            ));
        }
        if self.ingress.pending.len() == MAX_PENDING_CONTROLS {
            return Ok((
                ControlIngressAdmission::QueueFull,
                OutboundAckAdmission::NotEligible,
            ));
        }
        let id = self
            .ingress
            .next_id
            .checked_add(1)
            .ok_or_else(|| Error::new(Code::Quota, "control ingress ticket exhausted"))?;
        self.ingress.next_id = id;
        let domain = self.current_domain_id()?;
        self.ingress.pending.push_back(Pending {
            id,
            activity,
            domain,
            source,
            revision,
            bytes: Arc::from(bytes),
            leased: false,
        });
        Ok((
            ControlIngressAdmission::Queued,
            OutboundAckAdmission::NotEligible,
        ))
    }
    /// FIFO only after current authorization checks. Unverified bytes cannot claim exit priority.
    /// Removing a waiting stale item never replenishes rate tokens. Leased stale items still
    /// occupy slots until their worker returns/cancels, preventing unbounded in-flight jobs.
    pub fn next_control_verification(&mut self) -> Result<ControlVerificationPoll> {
        self.writable()?;
        let mut discarded = Vec::new();
        while let Some(index) = self.ingress.pending.iter().position(|p| !p.leased) {
            let pending = &self.ingress.pending[index];
            let context = self.control_ingress_context(pending.activity, pending.source);
            let refusal = match context {
                Ok(context)
                    if context.policy_revision == pending.revision
                        && pending.domain == self.current_domain_id()? =>
                {
                    None
                }
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
                    domain: pending.domain,
                    source: pending.source,
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
        if !Arc::ptr_eq(&job.owner, &self.ingress.owner)
            || job.domain != self.current_domain_id()?
        {
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
        self.finish_control_verification(job, outcome, neighbors, false)
            .map(|(completion, _)| completion)
    }

    /// A bound, newly inserted control object can queue one reply when its original
    /// acceptance transaction also created the source neighbor's responsibility.
    pub fn complete_control_verification_with_ack(
        &mut self,
        job: ControlVerificationJob,
        outcome: ControlVerificationOutcome,
        neighbors: &[ControlNeighbor],
    ) -> Result<(ControlVerificationCompletion, OutboundAckAdmission)> {
        self.finish_control_verification(job, outcome, neighbors, true)
    }

    fn finish_control_verification(
        &mut self,
        job: ControlVerificationJob,
        outcome: ControlVerificationOutcome,
        neighbors: &[ControlNeighbor],
        queue_ack: bool,
    ) -> Result<(ControlVerificationCompletion, OutboundAckAdmission)> {
        let pending = self.release_control_job(&job)?;
        if matches!(outcome, ControlVerificationOutcome::Rejected) {
            return Ok((
                ControlVerificationCompletion::Rejected,
                OutboundAckAdmission::NotEligible,
            ));
        }
        let ControlVerificationOutcome::Verified(object) = outcome else {
            unreachable!()
        };
        if let ControlSource::Channel(channel) = pending.source {
            self.ingress.require_channel(&channel)?;
        }
        if object.cose.as_slice() != pending.bytes.as_ref()
            || object.fields.activity != pending.activity
        {
            return Err(Error::new(
                Code::Conflict,
                "verified control differs from queued object",
            ));
        }
        let ack_channel = match pending.source {
            ControlSource::Channel(channel)
                if queue_ack
                    && neighbors
                        .iter()
                        .any(|neighbor| neighbor.participant == channel.peer)
                    && !(object.fields.kind == ControlKind::Exit
                        && object.fields.issuer == channel.peer_credential) =>
            {
                Some(channel)
            }
            _ => None,
        };
        let admission = self.policy_atomic(|s| {
            let context = s.control_ingress_context(pending.activity, pending.source)?;
            if context.policy_revision != pending.revision {
                return Err(Error::new(
                    Code::Conflict,
                    "control verification policy changed",
                ));
            }
            s.accept_control_in_transaction(
                &object,
                neighbors,
                ack_channel.map(|channel| channel.peer_credential),
            )
        })?;
        let ack = if let (ControlAdmission::Inserted(object_ref), Some(channel)) =
            (admission, ack_channel)
        {
            self.queue_committed_ack(
                pending.activity,
                channel,
                outbound_ack::AckTarget::Control(object_ref),
            )
        } else {
            OutboundAckAdmission::NotEligible
        };
        Ok((ControlVerificationCompletion::Accepted(admission), ack))
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
