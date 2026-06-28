# LinkedIn Resume Optimization and Application Automation System

This project is designed to automate the process of optimizing resumes and applying for jobs on LinkedIn. It leverages various components to analyze job descriptions, optimize resumes based on relevant keywords, and submit applications seamlessly.

## Project Structure

```
linkedin-resume-agent
├── src
│   ├── __init__.py
│   ├── main.py
│   ├── mcp
│   │   ├── __init__.py
│   │   └── mcp.py
│   ├── analyzers
│   │   ├── __init__.py
│   │   └── job_analyzer.py
│   ├── optimizers
│   │   ├── __init__.py
│   │   └── resume_optimizer.py
│   ├── submitters
│   │   ├── __init__.py
│   │   └── application_submitter.py
│   ├── scrapers
│   │   ├── __init__.py
│   │   └── job_scraper.py
│   ├── models
│   │   ├── __init__.py
│   │   ├── job.py
│   │   └── resume.py
│   └── utils
│       ├── __init__.py
│       └── config.py
├── tests
│   ├── __init__.py
│   ├── test_job_analyzer.py
│   ├── test_resume_optimizer.py
│   └── test_application_submitter.py
├── config
│   └── settings.yaml
├── requirements.txt
├── setup.py
├── .env.example
├── .gitignore
└── README.md
```

## Installation

1. Clone the repository:
   ```
   git clone <repository-url>
   ```
2. Navigate to the project directory:
   ```
   cd linkedin-resume-agent
   ```
3. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Usage

1. Configure your environment variables in the `.env` file based on the `.env.example` provided.
2. Run the application:
   ```
   python src/main.py
   ```

## Components

- **MCP**: The main controller that orchestrates the resume optimization and job application processes.
- **JobAnalyzer**: Analyzes job descriptions to extract relevant keywords.
- **ResumeOptimizer**: Optimizes resumes based on the extracted keywords.
- **ApplicationSubmitter**: Handles the submission of job applications.
- **JobScraper**: Scrapes job listings based on specified criteria.

## Testing

To run the tests, use the following command:
```
pytest
```

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any enhancements or bug fixes.

## License

This project is licensed under the MIT License. See the LICENSE file for details.