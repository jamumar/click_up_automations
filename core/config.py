# core/config.py
import os
from dotenv import load_dotenv

load_dotenv()

CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN")
ENV = os.getenv("ENV", "development")
CLICKUP_TEAM_ID = os.getenv("CLICKUP_TEAM_ID")
CLICKUP_LIST_ID = os.getenv("CLICKUP_LIST_ID", "")

if CLICKUP_LIST_ID is None:
    raise ValueError("CLICKUP_LIST_ID is not set in the .env file.")