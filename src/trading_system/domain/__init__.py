"""Domain entities from TZ v2.0 FINAL, section 5.

These models are the shared vocabulary between every stage (E-1..A2). They
carry no behavior beyond the invariants stated explicitly in the TZ; stage
logic (risk evaluation, execution, allocation, ...) lives in its own
package and is built only once its stage gate opens.
"""

from trading_system.domain.edge_thesis import EdgeThesis, EdgeThesisStatus, StructuralReason
from trading_system.domain.execution_specification import ExecutionSpecification
from trading_system.domain.hypothesis import Hypothesis, ResearchProtocol
from trading_system.domain.policy_envelope import AutonomyLevel, PolicyEnvelope
from trading_system.domain.protective_policy import ProtectivePolicy
from trading_system.domain.public_source import LegalUseStatus, PublicSource
from trading_system.domain.risk_decision import RiskDecision
from trading_system.domain.strategy_specification import StrategySpecification
from trading_system.domain.structured_event import StructuredEvent, ValidationStatus
from trading_system.domain.trade_intent import Side, TradeIntent

__all__ = [
    "AutonomyLevel",
    "EdgeThesis",
    "EdgeThesisStatus",
    "ExecutionSpecification",
    "Hypothesis",
    "LegalUseStatus",
    "PolicyEnvelope",
    "ProtectivePolicy",
    "PublicSource",
    "ResearchProtocol",
    "RiskDecision",
    "Side",
    "StrategySpecification",
    "StructuralReason",
    "StructuredEvent",
    "TradeIntent",
    "ValidationStatus",
]
