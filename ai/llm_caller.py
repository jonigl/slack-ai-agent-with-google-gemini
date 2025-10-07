import os
import re
from typing import List, Dict

from openai import OpenAI
from openai import Stream
from openai.types.responses import ResponseStreamEvent

DEFAULT_SYSTEM_CONTENT = """
You're an assistant in a Slack workspace.
Users in the workspace will ask you to help them write something or to think better about a specific topic.
You'll respond to those questions in a professional way.
When you include markdown text, convert them to Slack compatible ones.
When a prompt has Slack's special syntax like <@USER_ID> or <#CHANNEL_ID>, you must keep them as-is in your response.
"""


def call_llm(
    messages_in_thread: List[Dict[str, str]],
    system_content: str = DEFAULT_SYSTEM_CONTENT,
) -> Stream[ResponseStreamEvent]:
    openai_client = OpenAI(api_key=os.environ.get("GEMINI_API_KEY"), base_url=os.environ.get("GEMINI_API_BASE_URL"))
    messages = [{"role": "system", "content": system_content}]
    messages.extend(messages_in_thread)
    response = openai_client.chat.completions.create(
        model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        n=1,
        messages=messages,
        max_tokens=16384,
        stream=True
    )
    return response
