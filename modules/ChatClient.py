import os
from typing import List, Dict, Optional, Any
from openai import OpenAI

class ChatClient:
    """Reusable chat completion client."""

    def __init__(
        self,
        model: str = "gpt-5.1",
        system_prompt: str = "You are a helpful, precise assistant.",
        verbosity: str = "medium",
        effort: str = "medium",
    ):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.system_prompt = system_prompt
        self.verbosity = verbosity
        self.effort = effort

    def _build_messages(
        self,
        user_prompt: str,
        examples: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": self.system_prompt}]

        if examples:
            for ex in examples:
                messages.extend([
                    {"role": "user", "content": ex["user"]},
                    {"role": "assistant", "content": ex["assistant"]},
                ])

        messages.append({"role": "user", "content": user_prompt})
        return messages

    def generate(
        self,
        user_prompt: str,
        examples: Optional[List[Dict[str, str]]] = None,
        schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generates a response. If a schema is provided, the model 
        will output strictly valid JSON conforming to that schema.
        """
        messages = self._build_messages(user_prompt, examples)
        
        # 1. Define the base text configuration
        text_config = {"format": {"type": "text"}, "verbosity": self.verbosity}

        # 2. Inject schema correctly according to Responses API requirements
        if schema:
            text_config["format"] = {
                "type": "json_schema",
                "name": "data_extraction_schema", # name is a sibling of type here
                "schema": schema,                 # schema key contains the definition
                "strict": True
            }

        params = {
            "model": self.model,
            "input": messages,
            "text": text_config,  # Nested here
            "reasoning": {"effort": self.effort}
        }

        response = self.client.responses.create(**params)
        return response.output_text.strip()