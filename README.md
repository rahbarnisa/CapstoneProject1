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

## Functions
[3 tools called]

- `chat_completion_request` handles the raw POST to the Chat Completions API, including optional function descriptors, retrying on transient failures thanks to `tenacity`. It returns the HTTP response so other helpers can interpret it.

```16:35:main.py
@retry(wait=wait_random_exponential(min=1, max=40), stop=stop_after_attempt(3))
def chat_completion_request(messages, functions=None, model=MODEL):
    ...
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=json_data)
    return response
```

- `ask_database` is the single function advertised to the model; once invoked it executes whatever SQL string the model produced against the `netflix.db` SQLite file and returns the rows (or raises an error that later logic can fix).

```73:80:main.py
def ask_database(conn, query):
    results = conn.execute(query).fetchall()
    return results
```

- `chat_completion_with_function_execution` wraps one full turn with the model: it calls `chat_completion_request`, inspects whether the model wants to call a function, and either returns the text response or routes control to `call_function`.

```82:96:main.py
def chat_completion_with_function_execution(messages, functions=None):
    response = chat_completion_request(messages, functions)
    full_message = response.json()["choices"][0]
    if full_message["finish_reason"] == "function_call":
        return call_function(messages, full_message)
    ...
```

- `call_function` is the dispatcher that actually launches `ask_database` (the only supported tool), handles retry logic by asking the model to repair bad SQL, appends the function result back into the message list, and then asks the model to draft the final natural-language answer.

```99:152:main.py
def call_function(messages, full_message):
    if full_message["message"]["function_call"]["name"] == "ask_database":
        query = eval(...)
        results = ask_database(conn, query["query"])
        ...
        messages.append({"role": "function", "name": "ask_database", "content": str(results)})
        response = chat_completion_request(messages)
        return response.json()
```

- In `conversation.py`, the `Conversation` class provides two helper methods: `add_message` appends structured chat turns, and `display_conversation` prints them back with color-coding for each role so you can inspect the dialogue.

```4:25:conversation.py
class Conversation:
    def add_message(self, role, content):
        self.conversation_history.append({"role": role, "content": content})

    def display_conversation(self, detailed=False):
        for message in self.conversation_history:
            print(colored(f"{message['role']}: {message['content']}\n\n", role_to_color[message["role"]]))
```

Those are the main functions in this script and how each is used within the flow that answers the “top directors” question against the Netflix dataset.

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

