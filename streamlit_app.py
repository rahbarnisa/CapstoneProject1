import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = "gpt-4o-mini"
DATABASE = "data/netflix.db"
SUPPORT_TICKET_PATH = Path("data/support_tickets.csv")
MAX_ROWS = 200

DATABASE_SCHEMA = """
Table: netflix_titles
Columns: show_id, type, title, directors, cast, countries, date_added, release_year, rating, duration, listed_in, description
"""

SYSTEM_PROMPT = """You are DatabaseGPT, a helpful assistant that answers questions using the netflix_titles SQLite database.
Rules:
- Generate safe, single-statement, read-only SQL (SELECT ... or WITH ... SELECT) referencing only the netflix_titles table and its listed columns.
- Treat directors as a comma-separated list; when counting or grouping by director, expand the list using a CTE with json_each and TRIM, converting the string into valid JSON, for example:
  WITH director_cte AS (
      SELECT
          TRIM(value) AS director
      FROM netflix_titles,
           json_each(
               '["'
               || REPLACE(REPLACE(IFNULL(directors, ''), '"', ''), ',', '","')
               || '"]'
           )
      WHERE director <> ''
  )
- Apply sensible LIMIT values (e.g., 10 or 20) unless the user requests more.
- When results indicate data quality issues, suggest creating a support ticket through the provided tool.
Provide concise, markdown-formatted answers summarising the results."""

FUNCTIONS = [
    {
        "name": "ask_database",
        "description": "Use this function to answer user questions about the Netflix dataset. Output should be a fully formed SQL query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": f"""
                        SQL query extracting info to answer the user's question.
                        SQL must use this database schema:
                        {DATABASE_SCHEMA}
                        Return the query as plain text, not JSON.
                    """,
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_support_ticket",
        "description": "Create a support ticket for human follow-up when the data seems incorrect, incomplete, or when the user explicitly asks for human help.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short summary of the issue.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of the observed problem with necessary context.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "medium",
                    "description": "Priority of the ticket.",
                },
            },
            "required": ["title", "description"],
        },
    },
]


def _normalise_query(sql: str) -> str:
    if not sql:
        raise ValueError("Empty SQL query.")

    stripped = sql.strip()
    lowered = stripped.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("Only SELECT statements (optionally starting with WITH) are allowed.")

    replacement = (
        "'[\"' || REPLACE(REPLACE(IFNULL(directors, ''), '\"', ''), ',', '\",\"') || '\"]'"
    )
    safe_sql = stripped.replace("json_each(directors)", f"json_each({replacement})")
    safe_sql = safe_sql.replace("json_each(IFNULL(directors, ''))", f"json_each({replacement})")

    if safe_sql.strip().count(";") > 1:
        raise ValueError("Multiple statements are not allowed.")

    return safe_sql


def execute_query(sql: str):
    safe_sql = _normalise_query(sql)
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        logger.info("Executing SQL: %s", safe_sql)
        cursor.execute(safe_sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(MAX_ROWS)
        if cursor.fetchone():
            logger.warning("Result truncated to first %s rows to protect data.", MAX_ROWS)
            rows = rows[:MAX_ROWS]
    return columns, rows


def chat_completion_request(messages, functions=None, model=MODEL):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    payload = {"model": model, "messages": messages}
    if functions is not None:
        payload["functions"] = functions
    logger.info("Calling OpenAI with %s messages and %s tools.", len(messages), len(functions) if functions else 0)
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


def _ensure_ticket_store():
    SUPPORT_TICKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SUPPORT_TICKET_PATH.exists():
        SUPPORT_TICKET_PATH.write_text("ticket_id,title,description,priority,created_at\n", encoding="utf-8")


def create_support_ticket(title: str, description: str, priority: str = "medium") -> dict:
    _ensure_ticket_store()
    timestamp = datetime.utcnow().isoformat()
    ticket_id = f"T-{int(datetime.utcnow().timestamp())}"
    sanitized_title = title.replace("\n", " ").replace(",", " ")
    sanitized_description = description.replace("\n", " ").replace(",", " ")
    line = f"{ticket_id},{sanitized_title},{sanitized_description},{priority},{timestamp}\n"
    with SUPPORT_TICKET_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line)
    logger.info("Created support ticket %s with priority %s", ticket_id, priority)
    return {"ticket_id": ticket_id, "title": title, "priority": priority, "created_at": timestamp}


def run_agent(question: str):
    if not OPENAI_API_KEY:
        return {"error": "OPENAI_API_KEY is not set. Add it to your .env file."}

    logger.info("Received user question: %s", question)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    try:
        first_response = chat_completion_request(messages, FUNCTIONS)
    except requests.HTTPError as err:
        return {"error": f"OpenAI API error: {err.response.text}"}
    except Exception as err:
        return {"error": f"OpenAI request failed: {err}"}

    choice = first_response["choices"][0]
    finish_reason = choice.get("finish_reason")
    assistant_message = choice["message"]

    if finish_reason != "function_call":
        return {"text": assistant_message.get("content", "No response received.")}

    function_call = assistant_message.get("function_call", {})
    fn_name = function_call.get("name")

    if fn_name == "ask_database":
        try:
            arguments = json.loads(function_call.get("arguments", "{}"))
            query = arguments["query"]
        except Exception as err:
            return {"error": f"Failed to parse function arguments: {err}"}

        try:
            columns, rows = execute_query(query)
            result_payload = json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False)
        except Exception as err:
            return {"error": f"Database error: {err}"}

        messages.append(assistant_message)
        messages.append(
            {
                "role": "function",
                "name": "ask_database",
                "content": result_payload,
            }
        )

        try:
            follow_up = chat_completion_request(messages)
            final_text = follow_up["choices"][0]["message"].get("content", "").strip()
        except requests.HTTPError as err:
            return {"error": f"OpenAI API error on follow-up call: {err.response.text}", "columns": columns, "rows": rows}
        except Exception as err:
            return {"error": f"OpenAI follow-up failed: {err}", "columns": columns, "rows": rows}

        logger.info("Answered question with %s rows and message length %s", len(rows), len(final_text))
        return {"text": final_text, "columns": columns, "rows": rows, "query": query}

    if fn_name == "create_support_ticket":
        try:
            arguments = json.loads(function_call.get("arguments", "{}"))
        except Exception as err:
            return {"error": f"Failed to parse function arguments: {err}"}

        ticket = create_support_ticket(
            title=arguments.get("title", "Untitled issue"),
            description=arguments.get("description", ""),
            priority=arguments.get("priority", "medium"),
        )
        messages.append(assistant_message)
        messages.append(
            {
                "role": "function",
                "name": "create_support_ticket",
                "content": json.dumps(ticket, ensure_ascii=False),
            }
        )

        try:
            follow_up = chat_completion_request(messages)
            final_text = follow_up["choices"][0]["message"].get("content", "").strip()
        except Exception as err:
            final_text = f"Ticket created: {ticket['ticket_id']}. (Follow-up call failed: {err})"
        logger.info("Support ticket %s created via agent with priority %s", ticket["ticket_id"], ticket["priority"])
        return {"text": final_text, "ticket": ticket}

    return {"error": f"Unknown function requested: {fn_name}"}

@st.cache_data(show_spinner=False)
def get_dataset_summary():
    with sqlite3.connect(DATABASE) as conn:
        total_rows = conn.execute("SELECT COUNT(*) FROM netflix_titles").fetchone()[0]
        unique_titles = conn.execute("SELECT COUNT(DISTINCT title) FROM netflix_titles").fetchone()[0]
        latest_year = conn.execute("SELECT MAX(release_year) FROM netflix_titles").fetchone()[0]
        by_type = pd.read_sql_query(
            "SELECT type, COUNT(*) AS count FROM netflix_titles GROUP BY type ORDER BY count DESC",
            conn,
        )
    return {
        "total_rows": total_rows,
        "unique_titles": unique_titles,
        "latest_year": latest_year,
        "by_type": by_type,
    }


@st.cache_data(show_spinner=False)
def load_recent_tickets():
    if not SUPPORT_TICKET_PATH.exists():
        return pd.DataFrame(columns=["ticket_id", "title", "description", "priority", "created_at"])
    return pd.read_csv(SUPPORT_TICKET_PATH)


st.set_page_config(page_title="Netflix DB Assistant", layout="wide")
st.title("Netflix Titles Assistant")
st.caption("Ask questions about the Netflix catalog using natural language. Queries are executed safely via OpenAI function calling.")

summary = get_dataset_summary()

stats_col1, stats_col2, stats_col3 = st.columns(3)
stats_col1.metric("Rows in dataset", f"{summary['total_rows']:,}")
stats_col2.metric("Unique titles", f"{summary['unique_titles']:,}")
stats_col3.metric("Latest release year", summary["latest_year"])

with st.expander("Catalog composition by type", expanded=True):
    st.bar_chart(summary["by_type"], x="type", y="count")

with st.expander("Sample questions to try"):
    st.markdown(
        """
        - `Top 10 most common directors and their counts`
        - `How many titles were released each year after 2015?`
        - `Show the average rating per type (Movie vs TV Show)`
        - `List the top 5 countries by number of titles`
        """
    )

st.divider()

if not OPENAI_API_KEY:
    st.error("OPENAI_API_KEY is missing. Update your .env file and restart the app.")
    st.stop()

question = st.text_area("Ask a question", placeholder="e.g. Top 10 most common directors", height=120)

if st.button("Ask the agent"):
    if not question.strip():
        st.warning("Please enter a question before submitting.")
    else:
        with st.spinner("Thinking..."):
            result = run_agent(question.strip())

        if "error" in result:
            st.error(result["error"])
        else:
            if result.get("text"):
                st.markdown(result["text"])
            if result.get("columns") and result.get("rows"):
                df = pd.DataFrame(result["rows"], columns=result["columns"])
                st.dataframe(df, use_container_width=True)
            if result.get("query"):
                with st.expander("SQL executed"):
                    st.code(result["query"], language="sql")
            if result.get("ticket"):
                st.success(f"Support ticket created: {result['ticket']['ticket_id']} (priority: {result['ticket']['priority']})")

st.divider()

st.subheader("Need human help? File a support ticket")
with st.form("support_ticket_form"):
    ticket_title = st.text_input("Issue summary", placeholder="Short description of the problem")
    ticket_description = st.text_area("Details", placeholder="Explain what you observed and what you expected.")
    ticket_priority = st.selectbox("Priority", ["low", "medium", "high"], index=1)
    submit_ticket = st.form_submit_button("Create ticket")

if submit_ticket:
    if ticket_title.strip() and ticket_description.strip():
        ticket = create_support_ticket(ticket_title.strip(), ticket_description.strip(), ticket_priority)
        st.success(f"Ticket {ticket['ticket_id']} created. A human analyst will contact you soon.")
        load_recent_tickets.clear()
        logger.info("Manual ticket %s created from UI.", ticket["ticket_id"])
    else:
        st.warning("Please provide both a title and a description.")

with st.expander("Recent support tickets"):
    tickets_df = load_recent_tickets()
    if tickets_df.empty:
        st.write("No tickets created yet.")
    else:
        st.dataframe(tickets_df.sort_values("created_at", ascending=False).head(10))

