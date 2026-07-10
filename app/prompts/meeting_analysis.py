"""Prompt templates for transcript analysis."""

MEETING_ANALYSIS_SYSTEM_PROMPT = """
You are a precise meeting intelligence engine.
Return only valid JSON. Do not include markdown, commentary, or prose outside JSON.
Use concise, business-ready language.
If a section is not present in the transcript, return an empty list or empty string as appropriate.
""".strip()


def build_meeting_analysis_prompt(transcript: str) -> str:
    """Build the user prompt for structured meeting analysis."""
    return f"""
Analyze the meeting transcript and return this exact JSON structure:

{{
  "executive_summary": "string",
  "key_points": ["string"],
  "action_items": [
    {{
      "task": "string",
      "assignee": "string or null",
      "deadline": "ISO-8601 datetime/date string or null"
    }}
  ],
  "participants": ["string"],
  "key_decisions": ["string"],
  "deadlines": [
    {{
      "item": "string",
      "deadline": "ISO-8601 datetime/date string or null",
      "owner": "string or null"
    }}
  ],
  "risks": ["string"],
  "next_steps": ["string"]
}}

Transcript:
{transcript}
""".strip()
