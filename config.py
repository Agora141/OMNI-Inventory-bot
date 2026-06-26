import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]

SYSTEM_NAME  = os.getenv("SYSTEM_NAME", "Inventory Parts Manager")
SYSTEM_SHORT = os.getenv("SYSTEM_SHORT", "IPM")
DEFAULT_CAGE = os.getenv("DEFAULT_CAGE", "00000")

# Supabase
SUPABASE_URL        = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

GEMINI_API_KEY      = os.environ["GEMINI_API_KEY"]
OCR_MIN_TEXT_LENGTH = int(os.getenv("OCR_MIN_TEXT_LENGTH", "20"))

LOCAL_CSV_PATH = os.getenv("LOCAL_CSV_PATH", "parts_db.csv")

OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "en").split(",")
OCR_USE_GPU   = os.getenv("OCR_USE_GPU", "false").lower() == "true"

DEFAULT_CONDITION        = os.getenv("DEFAULT_CONDITION", "NOS")
DEFAULT_STORAGE_LOCATION = os.getenv("DEFAULT_STORAGE_LOCATION", "UNASSIGNED")
DEFAULT_UOM              = os.getenv("DEFAULT_UOM", "EA")
