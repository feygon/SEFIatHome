"""Validation layer subpackage for SEFI@Home.

Enforces quality and ethical constraints on submitted results before they
are written to the findings store: provenance checks, PII detection, and
(post-MVP) quorum validation.
"""

from sefi.validation.layer import (
    PIIMatch,
    ResultSubmission,
    ValidationLayer,
    ValidationResult,
)

__all__: list[str] = [
    "PIIMatch",
    "ResultSubmission",
    "ValidationLayer",
    "ValidationResult",
]
