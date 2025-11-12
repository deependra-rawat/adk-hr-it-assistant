import json
import os
import io
import pypdf
import csv
import re
import traceback
import requests

from typing import Optional
from pydantic import BaseModel, Field
from google.cloud import storage

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool,VertexAiSearchTool,agent_tool
from zeep import Client
from zeep.transports import Transport
from zeep.plugins import HistoryPlugin
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from vertexai.preview.language_models import TextEmbeddingModel
from google.cloud import discoveryengine_v1beta as discoveryengine

import os

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"D:\Projects\Godrej\GODREJ-BOT-main\service_account_key.json"

# Set your datastore ID and project
VERTEX_SEARCH_PROJECT = "generativeai-coe"
VERTEX_SEARCH_LOCATION = "global"
VERTEX_SEARCH_DATASTORE_ID = "datastore-1_1750920666730"
DATASTORE_ID = f"projects/{VERTEX_SEARCH_PROJECT}/locations/{VERTEX_SEARCH_LOCATION}/collections/default_collection/dataStores/{VERTEX_SEARCH_DATASTORE_ID}"

# --- Constants ---
APP_NAME = "agent_comparison_app"
DEFAULT_GCS_BUCKET = "godrej_adk11"
DEFAULT_GCS_BUCKET1 ="hr_docs_bucket1"

# --- GCS Client Setup ---
try:
    storage_client = storage.Client()
except Exception as e:
    print(f"ERROR: Could not initialize GCS client: {e}")
    storage_client = None

# --- Tool Functions ---

def perform_gcs_read_tool_function(bucket_name: str = DEFAULT_GCS_BUCKET) -> list:
    if storage_client is None:
        return [{"document": "N/A", "error": "Storage client not initialized"}]
    try:
        bucket = storage_client.bucket(bucket_name)
        blobs = list(bucket.list_blobs())
        if not blobs:
            return [{"document": "N/A", "status": "No documents found"}]
    except Exception as e:
        return [{"document": "N/A", "error": f"Failed to access bucket: {e}"}]

    results = []
    for blob in blobs:
        try:
            content = None
            if blob.name.lower().endswith(".pdf"):
                pdf_bytes = blob.download_as_bytes()
                reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                content = "\n".join(page.extract_text() or "" for page in reader.pages)
            elif blob.name.lower().endswith(('.txt', '.csv', '.json', '.xml', '.html')):
                content = blob.download_as_text()
            else:
                results.append({
                    "document": blob.name,
                    "status": "Skipped - Unsupported file type"
                })
                continue
            if content and content.strip():
                results.append({"document": blob.name, "content": content})
            else:
                results.append({"document": blob.name, "status": "Empty content"})
        except Exception as e:
            results.append({"document": blob.name, "error": str(e)})
    return results