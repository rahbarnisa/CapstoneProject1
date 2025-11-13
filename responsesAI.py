import sqlite3
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI()

MODEL = "gpt-4o-mini"
DATABASE = "data/netflix.db"

database_schema_string = """
Table: netflix_titles
Columns: show_id, type, title, directors, cast, countries, date_added, release_year, rating, duration, listed_in, description
"""

tools = [
    {
        "type": "function",
        "name": "ask_database",
        "description": "Get an answer from the SQL database based on a query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": f"""
                            SQL query extracting info to answer the user's question.
                            SQL should be written using this database schema:
                            {database_schema_string}
                            The query should be returned in plain text, not in JSON.
                            """,
                }
            },
            "required": ["query"],
        },
    },
]

def ask_database(query):
    conn = None
    try:
        conn = sqlite3.connect(DATABASE)
        print("Executing query: ", query)
        safe_query = query.replace(
            "json_each(directors)",
            "json_each('[\"' || REPLACE(REPLACE(IFNULL(directors, ''), '\"', ''), ',', '\",\"') || '\"]')"
        )
        safe_query = safe_query.replace(
            "json_each(IFNULL(directors, ''))",
            "json_each('[\"' || REPLACE(REPLACE(IFNULL(directors, ''), '\"', ''), ',', '\",\"') || '\"]')"
        )
        if safe_query != query:
            print("Adjusted query for safe JSON expansion.")
        results = conn.execute(safe_query).fetchall()
        print(f"Query returned {len(results)} rows.")
        return results
    except Exception as e:
        raise Exception(f"SQL error: {e}")
    finally:
        if conn is not None:
            conn.close()

messages = [
    {"role": "system", "content": """You are DatabaseGPT, a helpful assistant that answers questions using the netflix_titles SQLite database.
Rules:
- Generate safe, single-statement, read-only SQL (SELECT ... or WITH ... SELECT) referencing only the netflix_titles table and its listed columns.
- Treat directors as a comma-separated list; when counting or grouping by director, expand the list using a CTE with json_each and TRIM. Always wrap the directors field in IFNULL and convert it into valid JSON text before calling json_each, for example:
  WITH director_cte AS (
      SELECT
          show_id,
          TRIM(value) AS director
      FROM netflix_titles,
           json_each(
               '["'
               || REPLACE(REPLACE(IFNULL(directors, ''), '\"', ''), ',', '","')
               || '"]'
           )
      WHERE director <> ''
  )
- Apply sensible LIMIT values (e.g., 10) unless the user requests more.
Provide concise, markdown-formatted answers summarizing the results."""},
    {"role": "user", "content": "List the top 10 most common directors in the dataset along with their title counts."}
]

response = client.responses.create(
    model=MODEL,
    tools=tools,
    input=messages,
)

for item in response.output:
    if item.type == "function_call":
        if item.name == "ask_database":
            db_result = ask_database(json.loads(item.arguments)["query"])
            messages.append({"role": "assistant", "content": json.dumps(db_result, ensure_ascii=False)})
print(f"Messages count: {len(messages)}")

response = client.responses.create(
    model=MODEL,
    instructions="Respond to the user with the database results, format as markdown, and include the SQL query used if it was executed.",
    input=messages,
)

final_text = response.output_text
try:
    print("Final output:", final_text.encode("utf-8", errors="ignore").decode("utf-8"))
except Exception:
    print("Final output:", final_text)