"""
chat_client.py

Structured wrapper for OpenAI Chat Completions using model: gpt-5.1
"""

import os
from typing import List, Dict, Optional
from openai import OpenAI


class ChatClient:
    """Reusable chat completion client."""

    def __init__(
        self,
        model: str = "gpt-5.1",
        system_prompt: str = "You are a helpful, precise assistant.",
    ):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.system_prompt = system_prompt

    # -------------------------
    # Message Construction
    # -------------------------
    def _build_messages(
        self,
        user_prompt: str,
        examples: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        messages = [
            {"role": "system", "content": self.system_prompt}
        ]

        if examples:
            for ex in examples:
                messages.extend([
                    {"role": "user", "content": ex["user"]},
                    {"role": "assistant", "content": ex["assistant"]},
                ])

        messages.append({"role": "user", "content": user_prompt})
        return messages

    # -------------------------
    # Generation
    # -------------------------
    def generate(
        self,
        user_prompt: str,
        examples: Optional[List[Dict[str, str]]] = None,
    ) -> str:

        messages = self._build_messages(user_prompt, examples)

        response = self.client.responses.create(
            model=self.model,
            input=messages,
            text={
                "format": {
                    "type": "text"
                },
                "verbosity": "medium"
            },
            reasoning={
                "effort": "medium"
            },

        )

        return response.output_text.strip()

