"""Event journal primitives from TZ v2.0 FINAL, section 20.

The journal itself (append-only store, replay, upcasters) is Stage E0 work
and is gated on a CONFIRMED E-1 verdict (TZ 31). What lives here is only the
event vocabulary and envelope shape, which other stages need to agree on
before E0 exists.
"""

from trading_system.journal.events import EventEnvelope, EventType

__all__ = ["EventEnvelope", "EventType"]
