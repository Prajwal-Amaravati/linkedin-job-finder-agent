# LinkedIn Resume & Job Application Agent — AGENTS.md

This file provides context and conventions for AI coding assistants (Claude Code, Copilot, etc.) working in this repository.

---

## Project Overview

An end-to-end automation system that:
1. **Scrapes LinkedIn** for job listings matching Prajwal's profile (Senior Software Engineer / Tech Lead, geospatial focus)
2. **Runs CrewAI agents** (optional, `--crew` flag) to discover extra jobs via Google Search and gather company intelligence
3. **Optimizes the resume** with matched keywords per job
4. **Submits Easy Apply applications** on LinkedIn via browser automation (Playwright)
5. **Notifies via Telegram** with job details and tailored resume PDF

---

## Repository Layout

```
linkedin-resume-agent/
├── src/
│   ├── main.py                  # CLI entry point — orchestrates the whole pipeline
│   ├── agents/                  # CrewAI agents (optional, enabled via --crew flag)
│   │   ├── crew.py              # JobSearchCrew — orchestrates both agents
│   │   ├── job_research_agent.py  # Searches the web via SerperDevTool
│   │   └── company_intel_agent.py # Researches companies for resume tailoring
│   ├── analyzers/
│   │   └── job_analyzer.py      # Scores jobs by keyword relevance
│   ├── optimizers/
│   │   └── resume_optimizer.py  # Injects matched keywords into resume PDF
│   ├── scrapers/
│   │   └── job_scraper.py       # Scrapes LinkedIn via public API (no auth)
│   ├── submitters/
│   │   └── application_submitter.py  # Playwright Easy Apply automation
│   ├── notifiers/               # Telegram bot integration
│   ├── mcp/                     # MCP controller (legacy orchestration layer)
│   ├── models/
│   │   ├── job.py               # Job dataclass
│   │   └── resume.py            # Resume model
│   └── utils/
│       └── config.py            # Loads config/settings.yaml + .env
├── config/
│   └── settings.yaml            # All tuneable parameters (see below)
├── output/
│   ├── applications_log.csv     # Log of all submitted applications
│   └── resumes/                 # Tailored resume PDFs per job
├── logs/
│   └── agent.log                # Runtime log
├── tests/                       # pytest test suite
├── requirements.txt
├── .env.example                 # Copy to .env and fill in secrets
└── README.md
```

---

## Key Configuration (`config/settings.yaml`)

All pipeline behaviour is controlled here — **do not hardcode values in source files**.

| Section | Purpose |
|---|---|
| `candidate` | Name, email, resume PDF path, LinkedIn URL |
| `job_search.target_roles` | Ordered list of job titles to search for |
| `job_search.skill_keywords` | Skills used for relevance scoring |
| `job_search.domain_keywords` | Geospatial domain terms (boosts priority) |
| `job_search.locations` | Location preferences with priority scores |
| `job_search.excluded_companies` | Companies to skip entirely |
| `job_search.target_companies` | Companies to actively seek out |
| `crewai` | Model, temperature, search result count for agents |
| `application_submitter.dry_run` | Set `false` to actually submit applications |
| `telegram` | Bot token and chat_id for notifications |

---

## CrewAI Agents

These agents are **disabled by default** and enabled with the `--crew` CLI flag. They require `OPENAI_API_KEY` and `SERPER_API_KEY` in `.env`.

### 1. `JobResearchAgent` (`src/agents/job_research_agent.py`)
- **Role**: Senior Job Research Specialist
- **Tool**: `SerperDevTool` (Google Search API)
- **Goal**: Discovers job postings across the entire web — company career pages, Greenhouse, Lever, niche boards — beyond what LinkedIn scraping returns.
- **Output**: JSON list of `Job`-compatible dicts (title, company, location, url, description)
- **Parse**: `parse_results()` converts raw LLM output → `List[Job]`

### 2. `CompanyIntelAgent` (`src/agents/company_intel_agent.py`)
- **Role**: Company Intelligence Analyst
- **Tool**: `SerperDevTool`
- **Goal**: Researches target companies for tech stack, engineering culture, recent funding, and geospatial relevance.
- **Output**: JSON dict keyed by company name with fields: `tech_stack`, `engineering_culture`, `geospatial_relevance`, `recent_news`, `resume_keywords`, `priority_score`
- **Side effects**: `enrich_jobs_with_intel()` boosts job `relevance_score` and appends `resume_keywords` to `matched_skills`

### 3. `JobSearchCrew` (`src/agents/crew.py`)
- **Orchestrator**: Runs both agents sequentially via CrewAI `Process.sequential`
- **Pipeline**:
  1. `JobResearchAgent` → finds jobs
  2. `CompanyIntelAgent` → researches companies from found jobs + target list
  3. `enrich_jobs_with_intel()` → merges intelligence into Job objects
- **Returns**: `Tuple[List[Job], Dict[str, dict]]`

---

## Environment Variables (`.env`)

```bash
OPENAI_API_KEY=sk-...           # Required for CrewAI agent reasoning
SERPER_API_KEY=...              # Required for SerperDevTool (free tier at serper.dev)
LINKEDIN_EMAIL=...              # Used by Playwright Easy Apply
LINKEDIN_PASSWORD=...           # Used by Playwright Easy Apply
TELEGRAM_BOT_TOKEN=...          # Optional — overrides settings.yaml value
TELEGRAM_CHAT_ID=...            # Optional — overrides settings.yaml value
```

---

## Running the Pipeline

```bash
# Activate venv
source .venv/bin/activate

# Standard run (LinkedIn scraping only)
python src/main.py

# With CrewAI agents (web-wide search + company intel)
python src/main.py --crew

# Dry run (no actual applications submitted)
# Set dry_run: true in config/settings.yaml (default)

# Run tests
pytest
```

---

## Code Conventions

- **Config first**: All parameters from `config/settings.yaml` via `load_config()` — never hardcode job titles, URLs, or credentials.
- **Logging**: Use `logging.getLogger(__name__)` in every module. Log level controlled by `settings.yaml`.
- **Models**: `Job` and `Resume` are dataclasses in `src/models/`. Add fields there; do not create ad-hoc dicts.
- **Agent outputs**: Always go through `parse_results()` — the LLM may wrap JSON in markdown fences. Use regex extraction before `json.loads()`.
- **Dry run safety**: Check `application_submitter.dry_run` before any action that submits, clicks, or sends a message.
- **Rate limiting**: Respect `request_delay_seconds` (scraper) and `delay_between_actions` (submitter) to avoid account bans.
- **Tests**: Place unit tests in `tests/` using pytest. Mock external calls (LinkedIn, OpenAI, Serper).

---

## Common Tasks for AI Assistants

- **Add a new target company**: Edit `job_search.target_companies` in `config/settings.yaml`
- **Add a new skill keyword**: Edit `job_search.skill_keywords` in `config/settings.yaml`
- **Change the LLM model**: Edit `crewai.model` in `config/settings.yaml`
- **Add a new agent**: Create `src/agents/<name>_agent.py` following the pattern in `job_research_agent.py`, then wire it into `crew.py`
- **Add a new notification channel**: Add a class in `src/notifiers/` similar to the Telegram notifier
- **Debug agent output**: Check `logs/agent.log` and enable `crewai.verbose: true` in settings

---

## Known Gotchas

- LinkedIn scraping uses the **public guest API** (no login required). If responses return 429, increase `request_delay_seconds`.
- CrewAI agents may return JSON wrapped in markdown code fences — always use regex extraction in `parse_results()`.
- The Playwright Easy Apply flow is **highly sensitive to LinkedIn UI changes**. If it breaks, check `submitters/application_submitter.py` selectors.
- `dry_run: true` is the safe default — set it to `false` only when you are ready to submit real applications.
- Telegram `bot_token` is also stored in `settings.yaml` — prefer `.env` for secrets in production.
