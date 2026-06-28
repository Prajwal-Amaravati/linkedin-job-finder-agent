"""
Tests for CrewAI agent integration — uses mocked responses
to verify agent output parsing, Job model conversion, and
company intelligence enrichment without needing real API keys.
"""

import unittest
from unittest.mock import patch, MagicMock

from src.agents.job_research_agent import JobResearchAgent
from src.agents.company_intel_agent import CompanyIntelAgent
from src.models.job import Job


# ── Sample config matching real settings.yaml structure ────────────

MOCK_CONFIG = {
    "crewai": {
        "enabled": True,
        "model": "gpt-4o-mini",
        "temperature": 0.3,
        "max_search_results": 10,
        "verbose": False,
        "max_company_research": 3,
    },
    "job_search": {
        "target_roles": ["Senior Software Engineer", "Tech Lead"],
        "locations": [
            {"name": "United States", "priority": 1},
            {"name": "Remote", "priority": 1},
        ],
        "domain_keywords": ["geospatial", "GIS", "remote sensing"],
        "skill_keywords": ["Python", "FastAPI", "PostgreSQL", "AWS"],
        "excluded_companies": ["SatSure", "SkyServe"],
        "target_companies": ["Planet Labs", "Maxar Technologies", "Esri"],
    },
}


class TestJobResearchAgent(unittest.TestCase):
    """Test the Job Research Agent output parsing."""

    def setUp(self):
        self.agent = JobResearchAgent(MOCK_CONFIG)

    def test_parse_json_results(self):
        """Standard JSON array output."""
        raw = '''[
            {
                "title": "Senior Software Engineer",
                "company": "Planet Labs",
                "location": "San Francisco, CA",
                "url": "https://planet.com/careers/123",
                "description": "Build geospatial pipelines."
            },
            {
                "title": "Tech Lead - GIS Platform",
                "company": "Esri",
                "location": "Redlands, CA",
                "url": "https://esri.com/careers/456",
                "description": "Lead the GIS platform team."
            }
        ]'''
        jobs = self.agent.parse_results(raw)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].title, "Senior Software Engineer")
        self.assertEqual(jobs[0].company, "Planet Labs")
        self.assertEqual(jobs[0].location, "San Francisco, CA")
        self.assertTrue(jobs[0].job_id.startswith("crew_"))
        self.assertEqual(jobs[0].priority, 1)

    def test_parse_markdown_wrapped_json(self):
        """JSON wrapped in markdown code blocks (common LLM behavior)."""
        raw = '''Here are the jobs I found:

```json
[
    {
        "title": "Geospatial Engineer",
        "company": "Mapbox",
        "location": "Remote",
        "url": "https://mapbox.com/jobs/789",
        "description": "Work on mapping SDKs."
    }
]
```

These are the top results.'''
        jobs = self.agent.parse_results(raw)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "Mapbox")

    def test_parse_empty_output(self):
        """Empty or garbage output returns empty list."""
        self.assertEqual(self.agent.parse_results(""), [])
        self.assertEqual(self.agent.parse_results("No results found."), [])

    def test_parse_invalid_json(self):
        """Malformed JSON returns empty list."""
        jobs = self.agent.parse_results("[{broken json}]")
        self.assertEqual(len(jobs), 0)

    def test_job_id_uniqueness(self):
        """Different URLs produce different job IDs."""
        raw = '''[
            {"title": "SWE", "company": "A", "location": "X", "url": "https://a.com/1", "description": ""},
            {"title": "SWE", "company": "A", "location": "X", "url": "https://a.com/2", "description": ""}
        ]'''
        jobs = self.agent.parse_results(raw)
        self.assertNotEqual(jobs[0].job_id, jobs[1].job_id)

    def test_excluded_companies_in_task_description(self):
        """Verify search task includes excluded companies."""
        mock_agent = MagicMock()
        task = self.agent.create_search_task(mock_agent)
        self.assertIn("SatSure", task.description)
        self.assertIn("SkyServe", task.description)


class TestCompanyIntelAgent(unittest.TestCase):
    """Test the Company Intelligence Agent output parsing."""

    def setUp(self):
        self.agent = CompanyIntelAgent(MOCK_CONFIG)

    def test_parse_company_intel(self):
        """Standard JSON object output."""
        raw = '''{
            "Planet Labs": {
                "tech_stack": ["Python", "Kubernetes", "AWS", "TensorFlow"],
                "engineering_culture": "Agile, collaborative, strong code review culture",
                "geospatial_relevance": "Core satellite imagery and earth observation company",
                "recent_news": "Raised $200M Series E in 2023",
                "resume_keywords": ["satellite imagery", "cloud infrastructure", "data pipelines"],
                "priority_score": 9
            },
            "Esri": {
                "tech_stack": ["Python", "Java", "C++", "ArcGIS"],
                "engineering_culture": "Enterprise-scale, strong documentation",
                "geospatial_relevance": "World leader in GIS software",
                "recent_news": "Launched ArcGIS Pro 3.0",
                "resume_keywords": ["GIS", "spatial analysis", "enterprise software"],
                "priority_score": 8
            }
        }'''
        intel = self.agent.parse_results(raw)
        self.assertEqual(len(intel), 2)
        self.assertIn("Planet Labs", intel)
        self.assertEqual(intel["Planet Labs"]["priority_score"], 9)

    def test_parse_empty_output(self):
        """Empty output returns empty dict."""
        self.assertEqual(self.agent.parse_results(""), {})

    def test_enrich_jobs_with_intel(self):
        """Company intel enriches job objects with tech stack keywords."""
        jobs = [
            Job(
                job_id="test_1",
                title="Senior Engineer",
                company="Planet Labs",
                location="SF",
                description="Build things",
                url="https://planet.com/1",
                matched_skills=["Python"],
                relevance_score=50.0,
            ),
        ]
        intel = {
            "Planet Labs": {
                "tech_stack": ["Python", "Kubernetes"],
                "geospatial_relevance": "Core satellite imagery company",
                "resume_keywords": ["satellite imagery", "data pipelines"],
                "priority_score": 9,
            },
        }
        enriched = self.agent.enrich_jobs_with_intel(jobs, intel)
        self.assertTrue(enriched[0].is_geospatial)
        # Score should be boosted by 10 (priority_score >= 7)
        self.assertEqual(enriched[0].relevance_score, 60.0)
        # Should have added new keywords
        skills_lower = [s.lower() for s in enriched[0].matched_skills]
        self.assertIn("satellite imagery", skills_lower)
        self.assertIn("data pipelines", skills_lower)

    def test_enrich_no_matching_company(self):
        """Jobs from unknown companies remain unchanged."""
        jobs = [
            Job(
                job_id="test_2",
                title="Engineer",
                company="Unknown Corp",
                location="NY",
                description="",
                url="",
                relevance_score=30.0,
            ),
        ]
        intel = {
            "Planet Labs": {"resume_keywords": ["x"], "priority_score": 9},
        }
        enriched = self.agent.enrich_jobs_with_intel(jobs, intel)
        self.assertEqual(enriched[0].relevance_score, 30.0)
        self.assertFalse(enriched[0].is_geospatial)


if __name__ == "__main__":
    unittest.main()
