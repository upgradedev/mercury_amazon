"""
Institutional Memory & Post-Mortem RAG Domain Models (ACT-08).
Captures architectural scar tissue, root-cause analyses (RCA), and incident prevention vectors.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import time

@dataclass
class PostMortemIncident:
    incident_id: str
    title: str
    severity: str  # 'SEV-1', 'SEV-2', 'SEV-3'
    root_cause: str
    contributing_factors: List[str]
    preventive_architecture_changes: List[str]
    affected_services: List[str]
    occurred_at: str
    tags: List[str] = field(default_factory=list)
