# Netflix Titles Assistant

Minimal Streamlit experience for querying the `netflix_titles` dataset through an OpenAI-powered agent. The agent is configured for safe, read-only SQL function calling and can escalate issues by creating support tickets.

## Features

- Streamlit UI with dataset metrics, chart, sample questions, and ticket dashboard
- OpenAI function calling with two tools: `ask_database` (SQL) and `create_support_ticket`
- Safety guardrails: only single SELECT/WITH statements, results truncated to 200 rows, logging to console
- Support ticket creation (agent-triggered or manual) stored at `data/support_tickets.csv`
- Console logging for every request and SQL execution

## Requirements

- Python 3.11+
- OpenAI API key with access to `gpt-4o-mini`
- `data/netflix.db` SQLite file (already included, ~8.8k rows)

## Setup

```bash
# optional: create virtual environment
python -m venv .venv
.venv\Scripts\activate  # PowerShell / Cmd

# install dependencies
pip install -r requirements.txt  # or install packages listed below
pip install streamlit pandas requests python-dotenv openai tenacity termcolor

# configure secrets
copy .env.example .env   # or create .env manually
open .env                # add OPENAI_API_KEY, GITHUB_TOKEN (optional), SUPPORT_REPO (optional)
```

> The project currently stores the dataset and support tickets under `data/`. Keep this folder writable.

## Running the App

```bash
streamlit run streamlit_app.py
```

You’ll see:

1. Dataset metrics (row count, unique titles, latest release year) and catalog composition chart
2. Sample questions to copy/paste or adapt
3. Chat area to ask the agent. The agent may execute SQL and display the result table and the SQL used.
4. Support ticket form and list of the most recent tickets (`data/support_tickets.csv`)

Console output (in Terminal) traces each request and executed SQL for auditing.

## Support Tickets

- Agent-created tickets land in `data/support_tickets.csv` with timestamp and priority.
- Users can also file tickets manually in the UI when automated answers are insufficient.
- Extend `create_support_ticket` to integrate with GitHub/Jira/Trello webhooks if needed.

## Screenshots

Add real screenshots to demonstrate the workflow from launch → question → result → ticket creation. For example:

```
docs/
  workflow_overview.png
  agent_answer.png
  ticket_confirmation.png
```

Reference them here once captured:

![Workflow overview](docs/workflow_overview.png)
![Agent answer](docs/agent_answer.png)
![Ticket confirmation](docs/ticket_confirmation.png)

> Replace the placeholder images above with screenshots from your actual run to satisfy the assignment requirements.

## Troubleshooting

- **Module not found (streamlit/pandas/requests/python-dotenv)**: install dependencies inside your active virtual environment.
- **OpenAI error**: check `OPENAI_API_KEY` in `.env` and your OpenAI quota.
- **Database error**: ensure `data/netflix.db` exists and contains the expected schema.

## Extending

- Add authentication or role-based controls to restrict ticket creation.
- Push tickets to external systems (GitHub issues, Trello cards) instead of CSV.
- Deploy the app on Streamlit Community Cloud, Render, or HuggingFace Spaces for bonus credit.

## The Link to deployed WEB APP
https://capstoneproject1-fprjq4qybef9ydjfggt2jd.streamlit.app/

