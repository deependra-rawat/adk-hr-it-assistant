# ADK HR-IT Assistant 🤖

The **ADK HR-IT Assistant** is a multi-agent system built using the **ADK (Agent Development Kit)**.  
It provides intelligent support for both **HR-related** and **IT support** queries by integrating with tools such as **Vertex AI Search**, **BigQuery**, **GCS**, and **Remedy**.

---

## ⚙️ Features

- **HR Document QA**: Answers questions about HR policies, benefits, leaves, and onboarding using Vertex AI Search.
- **IT Support Assistant**: Handles IT-related queries (e.g., VPN, access issues, MS Teams problems) and can raise Remedy tickets automatically.
- **Email Summary Agent**: Generates and sends summarized support conversations as professional emails.
- **Memory Recall Agent**: Retrieves and summarizes past user conversations from BigQuery for continuity.
- **Tool Integration**: Connects with GCS, SMTP email services, and JIRA for real-world workflow automation.

---

## 🧩 Environment Setup

The system requires a few environment variables and configuration values for cloud services.

Example configuration snippet:

```python
DEFAULT_GCS_BUCKET = "your_gcs_bucket"
VERTEX_SEARCH_PROJECT = "your_project_id"
VERTEX_SEARCH_LOCATION = "global"
VERTEX_SEARCH_DATASTORE_ID = "your_datastore_id"

BQ_PROJECT = "your_project_id"
BQ_DATASET = "AgentDevelopmentKit"
BQ_TABLE = "convo_pairs"
