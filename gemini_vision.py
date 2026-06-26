import base64
import json
import logging
import re

import google.generativeai as genai

from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

genai.configure(api_key=GEMINI_API_KEY)
_model = genai.GenerativeModel("gemini-1.5-flash")

_PROMPT = """You are an expert parts specialist for industrial and military equipment.

Analyze the image and identify the part shown.
Respond with ONLY a valid JSON object — no markdown, no extra text.

{
  "found": true,
  "name": "full part name",
  "nsn": "XXXX-XX-XXX-XXXX or N/A",
  "part_number": "manufacturer part number or N/A",
  "category": "system the part belongs to",
  "confidence": "high / medium / low",
  "description": "brief identification notes",
  "condition_notes": "Good / Fair / Poor / Unknown"
}

If you cannot identify the part:
{"found": false, "description": "reason"}
"""


def identify_part_visually(image_path):
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()

        response = _model.generate_content(
            contents=[{
                "parts": [
                    {"text": _PROMPT},
                    {"inline_data": {
                        "mime_type": "image/jpeg",
                        "data": base64.b64encode(image_data).decode("utf-8"),
                    }},
                ]
            }],
            generation_config={"temperature": 0.1, "max_output_tokens": 512},
        )

        clean = re.sub(r"```(?:json)?|```", "", response.text.strip()).strip()
        data  = json.loads(clean)

        if not data.get("found"):
            return None

        return {
            "nsn":         data.get("nsn", "N/A"),
            "part_number": data.get("part_number", "N/A"),
            "name":        data.get("name", "Unknown"),
            "category":    data.get("category", ""),
            "confidence":  data.get("confidence", "low"),
            "description": data.get("description", ""),
            "condition":   data.get("condition_notes", "Unknown"),
            "source":      f"gemini ({data.get('confidence', 'low')})",
        }

    except json.JSONDecodeError:
        logger.error("gemini returned invalid json")
        return None
    except Exception as e:
        logger.exception("gemini error: %s", e)
        return None
