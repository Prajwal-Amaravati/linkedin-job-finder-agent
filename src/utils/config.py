import os
import yaml
import logging

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "settings.yaml",
)


def load_config(file_path: str = CONFIG_PATH) -> dict:
    """Load and return the YAML configuration."""
    with open(file_path, "r") as fh:
        config = yaml.safe_load(fh)
    logger.info("Configuration loaded from %s", file_path)
    return config


def get_database_config(config: dict) -> dict:
    return config.get("database", {})


def get_api_keys(config: dict) -> dict:
    return config.get("api_keys", {})


def get_job_scraper_settings(config: dict) -> dict:
    return config.get("job_scraper", {})


def get_job_search_criteria(config: dict) -> dict:
    return config.get("job_search", {})


def get_candidate_info(config: dict) -> dict:
    return config.get("candidate", {})


def get_resume_optimizer_settings(config: dict) -> dict:
    return config.get("resume_optimizer", {})


def get_application_submitter_settings(config: dict) -> dict:
    return config.get("application_submitter", {})


def setup_logging(config: dict) -> None:
    """Configure logging from config."""
    log_cfg = config.get("logging", {})
    log_level = getattr(logging, log_cfg.get("level", "INFO"))
    log_format = log_cfg.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    log_file = log_cfg.get("log_file")

    handlers = [logging.StreamHandler()]
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(level=log_level, format=log_format, handlers=handlers)