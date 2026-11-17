"""Shared model transport; task modules supply their own system prompt."""
import os
import json
import re
import urllib.request
from config import load_env


class LLMClient:
    def __init__(self, model, base_url, max_tokens, system_prompt):
        load_env()
        self.system_prompt = system_prompt
        self.model, self.base_url, self.max_tokens = model, base_url.rstrip('/'), max_tokens
        self.key = os.environ.get('LLM_API_KEY')
        if not self.key:
            raise ValueError('Set LLM_API_KEY before running with an API')

    def __call__(self, state):
        body = {'model': self.model, 'messages': [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': json.dumps(state, ensure_ascii=False)}],
            'max_tokens': self.max_tokens, 'temperature': 0}
        req = urllib.request.Request(self.base_url + '/chat/completions',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + self.key})
        with urllib.request.urlopen(req, timeout=180) as response:
            raw = json.load(response)
        content = raw['choices'][0]['message']['content']
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', content.strip())
        try:
            result = json.loads(text)
            if not isinstance(result, dict):
                raise ValueError('Expected JSON object')
            return result, raw.get('usage', {})
        except (ValueError, TypeError):
            return {'parse_error': content}, raw.get('usage', {})

