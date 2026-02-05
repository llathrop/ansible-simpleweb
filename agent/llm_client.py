import os
import re
import yaml
import logging
import json
from openai import OpenAI, APIConnectionError

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self, prompts_path='agent/prompts.yaml'):
        self.api_key = os.environ.get('LLM_API_KEY', 'sk-dummy') # Local servers often ignore this or need a dummy
        # Default: Ollama container in the same compose stack. Do NOT use localhost or host.docker.internal;
        # Ollama must run in the ollama container only. Override with LLM_API_URL if needed.
        self.base_url = os.environ.get('LLM_API_URL', 'http://ollama:11434/v1')
        # Default to a lightweight model; override with LLM_MODEL (e.g. qwen2.5-coder:7b for heavier use)
        self.model = os.environ.get('LLM_MODEL', 'qwen2.5-coder:1.5b')
        self.prompts_path = prompts_path
        self.prompts = self._load_prompts()
        
        logger.info(f"Initializing LLM Client: URL={self.base_url}, Model={self.model}")
        
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key
        )

    def _load_prompts(self):
        try:
            if os.path.exists(self.prompts_path):
                with open(self.prompts_path, 'r') as f:
                    data = yaml.safe_load(f) or {}
                    # Pre-process partials (e.g. {{ system_core }})
                    prompts = data.get('prompts', {})
                    system_core = prompts.get('system_core', '')
                    
                    for key, prompt_block in prompts.items():
                        if isinstance(prompt_block, dict) and 'system' in prompt_block:
                            # Replace {{ system_core }} in system prompts
                            prompt_block['system'] = prompt_block['system'].replace('{{ system_core }}', system_core)
                    
                    return data
            else:
                logger.warning(f"Prompts file not found at {self.prompts_path}")
                return {}
        except Exception as e:
            logger.error(f"Error loading prompts: {e}")
            return {}

    def reload_prompts(self):
        self.prompts = self._load_prompts()
        logger.info("Prompts reloaded")

    def analyze_log(self, job_id, playbook, exit_code, log_content):
        prompt_template = self.prompts.get('prompts', {}).get('default_log_review', {})
        if not prompt_template:
            logger.error("Default log review prompt not found")
            return None

        # Prepare messages
        system_msg = prompt_template.get('system', 'You are a helpful assistant.')
        user_template = prompt_template.get('user', '{{ log_content }}')
        
        # Simple template replacement
        user_msg = user_template.replace('{{ job_id }}', str(job_id))\
                                .replace('{{ playbook }}', str(playbook))\
                                .replace('{{ exit_code }}', str(exit_code))\
                                .replace('{{ log_content }}', log_content)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
                timeout=120
            )
            
            content = response.choices[0].message.content
            if not content or not content.strip():
                return {"error": "LLM returned empty response", "status": "failure"}
            # Reject prompt echo: if response looks like the user prompt, treat as invalid
            content_stripped = content.strip()
            if content_stripped.startswith("Here is the execution log") or "--- LOG START ---" in content_stripped[:500]:
                logger.warning("LLM echoed the prompt instead of generating analysis")
                return {"error": "Model returned prompt instead of analysis. Try a larger model (e.g. qwen2.5-coder:7b) via LLM_MODEL.", "status": "failure"}
            # Try to extract JSON (may be wrapped in ```json ... ```)
            json_str = content_stripped
            if "```" in content_stripped:
                m = re.search(r'```(?:json)?\s*([\s\S]*?)```', content_stripped)
                if m:
                    json_str = m.group(1).strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                logger.warning("LLM did not return valid JSON, returning helpful error")
                return {"error": "Model did not return valid JSON. Try a larger model (e.g. qwen2.5-coder:7b) via LLM_MODEL.", "status": "failure"}

        except APIConnectionError:
            msg = f"LLM Server Unreachable. Ensure the LLM container (e.g. Ollama service) is running and reachable at {self.base_url}."
            logger.error(msg)
            return {"error": msg, "status": "failure"}
        except Exception as e:
            logger.error(f"LLM inference failed: {e}")
            return {"error": str(e), "status": "failure"}

    def generate_playbook(self, request_text, context_text):
        prompt_template = self.prompts.get('prompts', {}).get('playbook_generation', {})
        if not prompt_template:
            logger.error("Playbook generation prompt not found")
            return None

        # Prepare messages
        system_msg = prompt_template.get('system', 'You are a helpful assistant.')
        user_template = prompt_template.get('user', '{{ request }}')
        
        # Simple template replacement
        user_msg = user_template.replace('{{ request }}', request_text)\
                                .replace('{{ context }}', context_text)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.7,
                timeout=120
            )
            
            return response.choices[0].message.content

        except APIConnectionError:
            msg = f"LLM Server Unreachable. Ensure the LLM container (e.g. Ollama service) is running and reachable at {self.base_url}."
            logger.error(msg)
            return msg
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"Error generating playbook: {e}"

    def analyze_config(self, config_content):
        prompt_template = self.prompts.get('prompts', {}).get('config_analysis', {})
        if not prompt_template:
            logger.error("Config analysis prompt not found")
            return {"error": "Prompt not found", "status": "failure"}

        # Prepare messages
        system_msg = prompt_template.get('system', 'You are a helpful assistant.')
        user_template = prompt_template.get('user', '{{ config_content }}')
        
        # Simple template replacement
        user_msg = user_template.replace('{{ config_content }}', config_content)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                timeout=120
            )
            
            content = response.choices[0].message.content
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                logger.warning("LLM did not return valid JSON for config analysis")
                return {"raw_response": content, "status": "parse_error"}

        except APIConnectionError:
            msg = f"LLM Server Unreachable. Ensure the LLM container (e.g. Ollama service) is running and reachable at {self.base_url}."
            logger.error(msg)
            return {"error": msg, "status": "failure"}
        except Exception as e:
            logger.error(f"LLM config analysis failed: {e}")
            return {"error": str(e), "status": "failure"}
