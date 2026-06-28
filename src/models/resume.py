from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Resume:
    """Represents a candidate resume with extracted content and keywords."""
    content: str
    keywords: list = field(default_factory=list)
    file_path: str = ""
    candidate_name: str = ""
    candidate_email: str = ""
    skills: list = field(default_factory=list)
    experience_years: int = 0

    def __repr__(self):
        return (
            f"Resume(candidate={self.candidate_name!r}, "
            f"keywords={len(self.keywords)}, skills={len(self.skills)})"
        )