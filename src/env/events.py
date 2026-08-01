"""
Typed events and the deterministic event queue (manuscript sec: event_process).

Decision events (eq:event_times discussion): UAV arrival, delivery completion,
depot return, completion of loading/charging, receipt of a P1/P2/P4 report,
and a change in route availability. P3 mutations and demand onsets are
*silent* truth-side events — under partial observability the controller
cannot react to what the command center has not observed (eq:p3_stale_belief).
Replenishments update depot state silently; the next decision observes them.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(Enum):
    # exogenous truth-side (silent, no decision)
    DEMAND_ONSET = "demand_onset"        # physical emergence (N(t) growth)
    P3_MUTATION = "p3_mutation"          # latent demand mutation
    REPLENISH = "replenish"              # depot replenishment R0_k(t)
    # exogenous information events (decision events)
    P1_REPORT = "p1_report"
    P2_REVEAL = "p2_reveal"
    P4_REPORT = "p4_report"
    AVAIL_CHANGE = "avail_change"
    # fleet events (decision events)
    UAV_ARRIVAL = "uav_arrival"          # arrival at a demand node
    SERVICE_COMPLETE = "service_complete"
    DEPOT_ARRIVAL = "depot_arrival"      # depot return
    LOAD_COMPLETE = "load_complete"      # loading + charging turnaround done
    # horizon guard
    HORIZON = "horizon"


# events applied at identical timestamps in this order: state updates first,
# then information receipt, then fleet decisions
_PRIORITY = {
    EventType.DEMAND_ONSET: 0,
    EventType.P3_MUTATION: 1,
    EventType.REPLENISH: 2,
    EventType.AVAIL_CHANGE: 3,
    EventType.P1_REPORT: 4,
    EventType.P2_REVEAL: 5,
    EventType.P4_REPORT: 6,
    EventType.UAV_ARRIVAL: 7,
    EventType.SERVICE_COMPLETE: 8,
    EventType.DEPOT_ARRIVAL: 9,
    EventType.LOAD_COMPLETE: 10,
    EventType.HORIZON: 11,
}

SILENT_TYPES = {EventType.DEMAND_ONSET, EventType.P3_MUTATION, EventType.REPLENISH}

# information events at which flying UAVs may re-decide (divert mid-leg)
INFO_DECISION_TYPES = {EventType.P1_REPORT, EventType.P2_REVEAL,
                       EventType.P4_REPORT, EventType.AVAIL_CHANGE}


@dataclass(frozen=True)
class Event:
    t: float
    etype: EventType
    payload: Dict[str, Any] = field(default_factory=dict)


class EventQueue:
    """Min-heap of events with deterministic (t, priority, insertion-seq) order."""

    def __init__(self):
        self._heap: List = []
        self._counter = itertools.count()
        self._cancelled: set = set()

    def push(self, ev: Event) -> int:
        seq = next(self._counter)
        heapq.heappush(self._heap, (ev.t, _PRIORITY[ev.etype], seq, ev))
        return seq

    def cancel(self, seq: int) -> None:
        """Lazy cancellation (used when a flying UAV diverts mid-leg)."""
        self._cancelled.add(seq)

    def pop(self) -> Optional[Event]:
        while self._heap:
            t, pr, seq, ev = heapq.heappop(self._heap)
            if seq in self._cancelled:
                self._cancelled.discard(seq)
                continue
            return ev
        return None

    def peek_time(self) -> Optional[float]:
        while self._heap:
            t, pr, seq, ev = self._heap[0]
            if seq in self._cancelled:
                heapq.heappop(self._heap)
                self._cancelled.discard(seq)
                continue
            return t
        return None

    def __len__(self) -> int:
        return len(self._heap) - len(self._cancelled)
