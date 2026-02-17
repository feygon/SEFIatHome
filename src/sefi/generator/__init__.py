"""Work unit generator subpackage for SEFI@Home.

Partitions the analysis corpus into self-contained work units that workers
claim and process without requiring direct database access.

Public API
----------
WorkUnit
    Dataclass representing a single unit of analytical work.
WorkUnitGenerator
    Generator class that creates and tracks ``verify_finding`` work units.
DE_ANON_PROHIBITION
    Verbatim de-anonymization prohibition text (EC-007) embedded in every
    generated unit's ``instructions`` field.
"""

from sefi.generator.units import DE_ANON_PROHIBITION, WorkUnit, WorkUnitGenerator

__all__: list[str] = [
    "WorkUnit",
    "WorkUnitGenerator",
    "DE_ANON_PROHIBITION",
]
