"""Quick test: verify imports, PDF generation, and Telegram notifier setup."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notifiers.telegram_notifier import TelegramNotifier
from src.optimizers.resume_optimizer import ResumeOptimizer
from src.models.job import Job
from src.mcp.mcp import MCP

print("✅ All imports successful")

# Test PDF generation
opt = ResumeOptimizer()
opt.load_resume()

test_job = Job(
    job_id="test123",
    title="Senior Geospatial Engineer",
    company="Planet Labs",
    location="San Francisco, CA",
    description="We need a Senior Engineer with Python, AWS, Kubernetes, Docker, geospatial processing, PostGIS, STAC, satellite imagery, distributed systems, Airflow, and Terraform experience.",
    url="https://linkedin.com/jobs/view/test123",
    matched_skills=["python", "aws", "kubernetes", "docker", "geospatial", "postgis", "stac", "airflow", "terraform"],
    is_geospatial=True,
    relevance_score=85.5,
    priority=1,
)

pdf_path = opt.generate_tailored_pdf(test_job)
print(f"✅ PDF generated: {pdf_path}")
print(f"   Size: {os.path.getsize(pdf_path)} bytes")

# Verify Telegram module loads correctly
tg = TelegramNotifier()
print(f"✅ TelegramNotifier loaded (enabled={tg.enabled})")
print()
print("All tests passed! To enable Telegram, run:")
print("  python -m src.main --setup-telegram")
