//! Pure scheduling rules ported from I1. A decision is not a send permission.
use crate::error::{Code, Error, Result};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Link {
    Up,
    Down,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum LinkEvent {
    Unchanged,
    Up,
    Down,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Signal {
    Continue,
    Pause,
    Stop,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Admission {
    Allow,
    Quota,
    Hop,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Batch {
    pub now_ms: i64,
    pub link: LinkEvent,
    pub signal: Signal,
    pub admission: Admission,
}
impl Batch {
    /// Merge observations before advancing a queue. Contradictory link observations
    /// require an ordered platform batch; silently choosing one would create a retry.
    pub fn merge(self, other: Self) -> Result<Self> {
        if self.now_ms != other.now_ms || self.now_ms < 0 {
            return Err(Error::new(Code::Conflict, "event batch time"));
        }
        let link = match (self.link, other.link) {
            (LinkEvent::Unchanged, value) | (value, LinkEvent::Unchanged) => value,
            (a, b) if a == b => a,
            _ => {
                return Err(Error::new(
                    Code::Conflict,
                    "contradictory link observations",
                ));
            }
        };
        let signal = match (self.signal, other.signal) {
            (Signal::Stop, _) | (_, Signal::Stop) => Signal::Stop,
            (Signal::Pause, _) | (_, Signal::Pause) => Signal::Pause,
            _ => Signal::Continue,
        };
        let admission = match (self.admission, other.admission) {
            (Admission::Quota, _) | (_, Admission::Quota) => Admission::Quota,
            (Admission::Hop, _) | (_, Admission::Hop) => Admission::Hop,
            _ => Admission::Allow,
        };
        Ok(Self {
            now_ms: self.now_ms,
            link,
            signal,
            admission,
        })
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
enum Phase {
    Active,
    Paused,
    Stopped,
    Expired,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RetryState {
    version: u8,
    start_ms: i64,
    deadline_ms: i64,
    next_slot: usize,
    recovery_used: bool,
    link: Link,
    phase: Phase,
    last: Option<Batch>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Reason {
    Waiting,
    Exhausted,
    Sending,
    LinkDown,
    Quota,
    Hop,
    Paused,
    Stopped,
    Expired,
    Duplicate,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Decision {
    pub send: bool,
    pub consumed: usize,
    pub recovery_consumed: bool,
    pub reason: Reason,
}
impl Decision {
    fn idle(reason: Reason) -> Self {
        Self {
            send: false,
            consumed: 0,
            recovery_consumed: false,
            reason,
        }
    }
}
impl RetryState {
    pub(crate) fn deadline_ms(&self) -> i64 {
        self.deadline_ms
    }
    /// Migration may shorten validity, never replenish any retry or change its origin.
    pub(crate) fn constrain_deadline(&mut self, deadline_ms: i64) -> Result<()> {
        if deadline_ms < 0 {
            return Err(Error::new(Code::InvalidInput, "retry deadline bound"));
        }
        self.deadline_ms = self.deadline_ms.min(deadline_ms);
        self.validate()
    }
    pub fn new(start_ms: i64, deadline_ms: i64, link: Link) -> Result<Self> {
        let s = Self {
            version: 1,
            start_ms,
            deadline_ms,
            next_slot: 0,
            recovery_used: false,
            link,
            phase: Phase::Active,
            last: None,
        };
        s.validate()?;
        Ok(s)
    }
    pub fn validate(&self) -> Result<()> {
        if self.version != 1
            || self.start_ms < 0
            || self.start_ms > i64::MAX - 3750
            || self.deadline_ms < 0
            || self.next_slot > 5
            || self.last.is_some_and(|b| b.now_ms < 0)
            || (self.last.is_none()
                && (self.next_slot != 0 || self.recovery_used || self.phase != Phase::Active))
        {
            return Err(Error::new(Code::InvalidInput, "retry state"));
        }
        Ok(())
    }
    pub fn advance(&self, b: Batch) -> Result<(Self, Decision)> {
        self.validate()?;
        if b.now_ms < 0 {
            return Err(Error::new(Code::InvalidInput, "retry time"));
        }
        if let Some(last) = self.last {
            if b.now_ms < last.now_ms {
                return Err(Error::new(Code::TimeUncertain, "retry clock"));
            }
            if b.now_ms == last.now_ms {
                return if b == last {
                    Ok((self.clone(), Decision::idle(Reason::Duplicate)))
                } else {
                    Err(Error::new(Code::Conflict, "retry batch"))
                };
            }
        }
        let mut next = self.clone();
        next.last = Some(b);
        let terminal = if next.phase == Phase::Stopped || b.signal == Signal::Stop {
            next.phase = Phase::Stopped;
            Some(Reason::Stopped)
        } else if next.phase == Phase::Expired {
            Some(Reason::Expired)
        } else if next.phase == Phase::Paused || b.signal == Signal::Pause {
            next.phase = Phase::Paused;
            Some(Reason::Paused)
        } else if b.now_ms >= next.deadline_ms {
            next.phase = Phase::Expired;
            Some(Reason::Expired)
        } else {
            None
        };
        if let Some(r) = terminal {
            return Ok((next, Decision::idle(r)));
        }
        let recovered = next.link == Link::Down && b.link == LinkEvent::Up;
        match b.link {
            LinkEvent::Up => next.link = Link::Up,
            LinkEvent::Down => next.link = Link::Down,
            _ => {}
        }
        if b.now_ms < next.start_ms {
            return Ok((next, Decision::idle(Reason::Waiting)));
        }
        let mut d = Decision::idle(Reason::Waiting);
        for offset in [0, 250, 750, 1750, 3750].into_iter().skip(next.next_slot) {
            if b.now_ms < next.start_ms + offset {
                break;
            }
            next.next_slot += 1;
            d.consumed += 1;
        }
        if recovered && !next.recovery_used {
            next.recovery_used = true;
            d.recovery_consumed = true;
        }
        if d.consumed == 0 && !d.recovery_consumed {
            if next.next_slot == 5 {
                d.reason = Reason::Exhausted;
            }
        } else if next.link == Link::Down {
            d.reason = Reason::LinkDown;
        } else {
            d.reason = match b.admission {
                Admission::Allow => {
                    d.send = true;
                    Reason::Sending
                }
                Admission::Quota => Reason::Quota,
                Admission::Hop => Reason::Hop,
            };
        }
        Ok((next, d))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn batch(now_ms: i64) -> Batch {
        Batch {
            now_ms,
            link: LinkEvent::Unchanged,
            signal: Signal::Continue,
            admission: Admission::Allow,
        }
    }
    #[test]
    fn late_batch_consumes_slots_without_burst_and_recovers_once() {
        let s = RetryState::new(0, 10000, Link::Down).unwrap();
        let (s, d) = s.advance(batch(4000)).unwrap();
        assert_eq!(d.consumed, 5);
        assert!(!d.send);
        let (s, d) = s
            .advance(Batch {
                link: LinkEvent::Up,
                ..batch(5000)
            })
            .unwrap();
        assert!(d.send && d.recovery_consumed);
        let (s, _) = s
            .advance(Batch {
                link: LinkEvent::Down,
                ..batch(6000)
            })
            .unwrap();
        let (_, d) = s
            .advance(Batch {
                link: LinkEvent::Up,
                ..batch(7000)
            })
            .unwrap();
        assert!(!d.send);
    }
    #[test]
    fn stop_pause_duplicate_and_time_boundaries() {
        let s = RetryState::new(0, 100, Link::Up).unwrap();
        let (s, _) = s
            .advance(Batch {
                signal: Signal::Pause,
                ..batch(0)
            })
            .unwrap();
        let (s, d) = s
            .advance(Batch {
                signal: Signal::Stop,
                ..batch(100)
            })
            .unwrap();
        assert_eq!(d.reason, Reason::Stopped);
        assert_eq!(
            s.advance(Batch {
                signal: Signal::Stop,
                ..batch(100)
            })
            .unwrap()
            .1
            .reason,
            Reason::Duplicate
        );
        assert!(s.advance(batch(100)).is_err());
        assert!(s.advance(batch(99)).is_err());
        assert_eq!(
            RetryState::new(0, 100, Link::Up)
                .unwrap()
                .advance(batch(100))
                .unwrap()
                .1
                .reason,
            Reason::Expired
        );
        assert!(RetryState::new(i64::MAX, i64::MAX, Link::Up).is_err());
    }
    #[test]
    fn quota_and_hop_consume_opportunity() {
        for admission in [Admission::Quota, Admission::Hop] {
            let (s, d) = RetryState::new(0, 10000, Link::Up)
                .unwrap()
                .advance(Batch {
                    admission,
                    ..batch(0)
                })
                .unwrap();
            assert!(!d.send);
            assert_eq!(d.consumed, 1);
            assert!(!s.advance(batch(1)).unwrap().1.send);
        }
    }
}
