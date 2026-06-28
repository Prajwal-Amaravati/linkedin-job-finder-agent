from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Job:
    """Represents a single job listing scraped from LinkedIn."""
    job_id: str
    title: str
    company: str
    location: str
    description: str
    url: str
    date_posted: str = ""
    experience_level: str = ""
    job_type: str = ""
    industry: str = ""
    # Populated after analysis
    relevance_score: float = 0.0
    is_geospatial: bool = False
    matched_skills: list = field(default_factory=list)
    priority: int = 99  # 1 = highest

    def __repr__(self):
        return (
            f"Job(id={self.job_id}, title={self.title!r}, "
            f"company={self.company!r}, location={self.location!r}, "
            f"score={self.relevance_score:.2f}, priority={self.priority})"
        )