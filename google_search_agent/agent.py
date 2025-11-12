import re
import traceback
import requests
import os
import uuid

from typing import Optional, List
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool, VertexAiSearchTool, agent_tool
from google.cloud import bigquery

from tools.perform_gcs_tool import perform_gcs_read_tool_function
from tools.email_tools import send_email_via_smtp
from tools.remedy_tools import create_remedy_incident

# ──────────────────────────────────────────────
# Environment Setup
# ──────────────────────────────────────────────
DEFAULT_GCS_BUCKET = "godrej_adk11"
DEFAULT_GCS_BUCKET1 = "hr_docs_bucket1"

VERTEX_SEARCH_PROJECT = "generativeai-coe"
VERTEX_SEARCH_LOCATION = "global"
VERTEX_SEARCH_DATASTORE_ID = "datastore-1_1750920666730"
DATASTORE_ID = f"projects/{VERTEX_SEARCH_PROJECT}/locations/{VERTEX_SEARCH_LOCATION}/collections/default_collection/dataStores/{VERTEX_SEARCH_DATASTORE_ID}"

BQ_PROJECT = "generativeai-coe"
BQ_DATASET = "AgentDevelopmentKit"
BQ_TABLE = "convo_pairs_rajat"

# ──────────────────────────────────────────────
# Tool Wrapping
# ──────────────────────────────────────────────
gcs_tool = FunctionTool(perform_gcs_read_tool_function)
remedy_tool = FunctionTool(create_remedy_incident)
email_tool = FunctionTool(send_email_via_smtp)

vertex_search_tool = VertexAiSearchTool(data_store_id=DATASTORE_ID)

# ──────────────────────────────────────────────
# HR Document QA Agent
# ──────────────────────────────────────────────
doc_qa_agent = LlmAgent(
    name="hr_doc_qa_agent",
    model="gemini-2.0-flash",
    tools=[vertex_search_tool],
    instruction=f"""You are an HR support assistant specialized in answering queries related to HR policies, benefits, holidays, salary, onboarding, and exit process using HR documents found in the datastore: {DATASTORE_ID}.
Always use the Vertex Search tool to find relevant document snippets and answer based strictly on them.
If you can't find the answer in the documents, say clearly that the information could not be found.
""",
    description="Provides HR policy-related answers by searching HR documents using Vertex AI Search."
)

# ──────────────────────────────────────────────
# Email Summary Agent
# ──────────────────────────────────────────────
email_summary_agent = LlmAgent(
    name="email_summary_agent",
    model="gemini-2.0-flash",
    tools=[email_tool],
    instruction="""
You are a professional support assistant tasked with generating a conversation summary in the form of an email written FROM the user TO the support team.

When the user requests a conversation summary:
1. Analyze the entire conversation history available in this session.
2. Identify and summarize:
   - The user's issue(s)
   - The troubleshooting steps provided
   - The outcome of those steps (whether resolved or not)
   - Any HR-related queries and answers shared

3. Write a polite and professional email structured as follows:
   - A greeting.
   - A clear subject line.
   - An email body that includes:
       • A brief introduction stating the user is writing to summarize a support interaction
       • The issue they faced
       • The steps they tried based on the assistant’s suggestions
       • Whether the issue was resolved or not
       • Any HR queries they asked and the answers provided
       • A closing note asking for further help if needed

4. Sign the email as if written by the user (e.g., "Regards, [User Name]" — use a placeholder if not known)

5. Once the summary email is generated, immediately call the send_email_via_smtp tool using:
   - subject: the subject line you created
   - body: the email body you wrote

IMPORTANT: Do not use a default example issue like "unable to access the portal". Only summarize actual issues and steps from the user's conversation in this session.
Make sure the tone of the email is that of the **user reporting or escalating** their issue to the support team.
"""
)

# ──────────────────────────────────────────────
# Load Conversation History from BigQuery
# ──────────────────────────────────────────────
def load_user_history_from_bq(user_id: str):
    """
    Fetches user conversation history and formats it into a clean string for the LLM.
    """
    client = bigquery.Client()
    query = f"""
WITH session_latest AS (
  SELECT
    session_id,
    MAX(timestamp) AS latest_timestamp
  FROM {BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}
  WHERE user_id = '{user_id}'
  GROUP BY session_id
),

-- Step 2: Rank sessions by latest timestamp (most recent first)
ranked_sessions AS (
  SELECT
    session_id,
    RANK() OVER (ORDER BY latest_timestamp DESC) AS session_rank
  FROM session_latest
),

-- Step 3: Join back to the main table to get messages from top 3 sessions
final_sessions AS (
  SELECT
    c.session_id,
    c.user_agent_pairs,
    c.timestamp,
    r.session_rank
  FROM {BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE} c
  JOIN ranked_sessions r
    ON c.session_id = r.session_id
  WHERE c.user_id = '{user_id}'
)

-- Step 4: Only keep messages from top 3 sessions
SELECT *
FROM final_sessions
WHERE session_rank <= 3
ORDER BY session_rank, timestamp
    """
    try:
        result = client.query(query).result()
        rows = list(result)  # Consume iterator to check if it's empty

        if not rows:
            return "No past conversation history was found for this user."

        # Pre-process the history into a single, clean string
        formatted_history = ""
        for i, row in enumerate(rows):
            formatted_history += f"--- Conversation Session {i+1} ---\n"
            conversation_pairs = row["user_agent_pairs"]
            
            # Check if the data is in the expected list-of-dicts format
            if isinstance(conversation_pairs, list):
                for pair in conversation_pairs:
                    user_query = pair.get('user', 'N/A')
                    # Flatten newlines in agent response for cleaner output
                    agent_response = pair.get('agent', 'N/A').replace('\n', ' ') 
                    formatted_history += f"User: {user_query}\nAgent: {agent_response}\n"
            
            formatted_history += "\n"

        # This print statement is for your debugging
        print("Formatted Past Convos ---------->\n", formatted_history)
        return formatted_history

    except Exception as e:
        print(f"An error occurred in load_user_history_from_bq: {traceback.format_exc()}")
        return "Sorry, I encountered an error while trying to retrieve your history."

# ──────────────────────────────────────────────
# Search the big query for past conversations
# ──────────────────────────────────────────────
memory_recall_agent = LlmAgent(
    model="gemini-2.0-flash",
    name="MemoryRecallAgent",
    description=(
        "Agent to answer questions about BigQuery data and models and execute"
        " SQL queries."
    ),
    instruction="""
You are a helpful assistant that summarizes past conversations session by session.

1. When the user asks about previous conversations, call the BigQuery toolset and use `load_user_history_from_bq` to fetch session-wise chat history.
2. The tool returns a list of sessions; each session contains the full turn-by-turn dialogue.
3. Analyze **each session independently**, identifying only what was discussed in that session.
4. Formulate a human-readable summary that reflects **only the content of each session**, without assuming facts from others.
5. When summarizing, mention the session number and what was discussed, e.g., “Session 1: Only greetings were exchanged.”
6. Do not mix or merge events from different sessions unless the user explicitly asks for a high-level overview.
7. If the history is empty, simply respond that you don't have a record of any past conversations.

Never output raw data or internal structures. Keep summaries concise, accurate, and user-friendly.
""",
    tools=[FunctionTool(load_user_history_from_bq)] # Give the agent the tool
)

# ──────────────────────────────────────────────
# Root Agent
# ──────────────────────────────────────────────
def build_root_agent(user_id: str) -> LlmAgent:

    return LlmAgent(
        model="gemini-2.0-flash-exp",
        name="capital_agent",
        instruction=f"""
You are an IT Admin support assistant.

If user input is a greeting (hi, hello, hey, good morning, etc.), reply with suitable greetings and how can I help with IT Support.
- If the query is related to HR (e.g., leave policy, salary, holidays, employee benefits, onboarding, exit process):
    1. Use hr_doc_qa_agent to search the relevant documents.
    2. Provide concise and accurate answers based on the document.
- If the user's question seems related to something they've previously asked, 
use the 'memory_recall_agent' to retrieve the user's history and use that to inform your answer. 
Make sure to pass the {user_id}.
- If the query is related to IT support (e.g., VPN, MS Teams, access issues, laptop problems, software/tools):
    Follow these steps:

    1. Analyze the issue. If it’s clearly not related to HR or IT support (e.g., cafeteria, travel, general requests), respond:
       "This appears to be outside the scope of HR or IT support. Please contact the appropriate department."

2. Provide a single suggestion to help address the issue.
3. Then ask: "Did this solve your issue?"
4. If the user says "No give more suggestion" or phrases like "more suggestion":
    - Provide only one more suggestion.
    - Then ask again: "Did this solve your issue?"
    - If the user says "No" to this second suggestion, then directly execute steps from 5.a below.
5. If the user says "no" or phrases like "No, it didnt solved":
    a. Use perform_gcs_read_tool_function to fetch GCS documents.
    b. Refer to the CSV content, understand the user query and then check the 'services' and 'issues' columns of the document and find the exact problem by analyzing the user queries.
        First understanding the user query
        Extract the parameters in the following format:
        service = "<Name of the most probable service that is impacted>"
        issue = "<Most probable issue that you found post matching with PDF>"
        I want precise answers not long answers.
        Then ask:
        "I understand that your issue is [issue], and the corresponding service is [service]. Is that correct?"
        If user says "yes", "yes, correct" or "correct" then perform following steps:
            1. Again refer to the CSV content with the issue and service keyword and extract the corresponding support team from SupportTeam column.
            2. If support team found, say:
               The support team for [issue] is [Team Name]. Would you like me to create an incident ticket to them? If yes, say create a ticket.
6. If user says "create a ticket":
    a. Create a Python dictionary named summary_data with the following format:
    summary_data = {{
        "Issue": "<issue>",
        "Service": "<service>",
        "SupportTeam": "<Team Name>",
        "UserEmailBody": "<email body from user's perspective, do not include subject here>",
        "Subject": "<subject from user's perspective>"
    }}
    b. Then call the function: create_remedy_incident(summary_data) to create remedy ticket

7. If the issue is unclear: ask the user for more detail and specify the service/device (e.g., MS Teams, VPN, etc.).
8. Whenever user ask to summarise the conversation then:
    - Use email_summary_agent to generate the summary from the conversation and for sending an email.
""",
        tools=[
            gcs_tool,
            agent_tool.AgentTool(agent=doc_qa_agent),
            remedy_tool,
            agent_tool.AgentTool(agent=email_summary_agent),
            agent_tool.AgentTool(agent=memory_recall_agent),
        ]
    )

# Entry point for import
root_agent = build_root_agent

print("✅ LlmAgent in agent.py successfully configured with BQ history and custom tools.")
