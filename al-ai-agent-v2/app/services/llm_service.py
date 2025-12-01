"""
LLM service using OpenRouter for unified model access
"""
import os
from typing import Dict, List, Optional, Any, Iterator
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from dotenv import load_dotenv
import json

load_dotenv()

class LLMService:
    """Unified LLM service using OpenRouter"""
    
    def __init__(self):
        """
        Initialize LLM service with OpenRouter configuration
        """
        self.api_key = os.getenv("OPEN_ROUTER_KEY")
        if not self.api_key:
            # Fallback for legacy setups or development, though plan requires it.
            # We'll log a warning or raise if strictly enforcing.
            # For now, let's assume it might be missing in some legacy envs but we want to fail fast if used.
            pass

        self.base_url = os.getenv("OPEN_ROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.default_model = os.getenv("DEFAULT_MODEL_VERSION", "google/gemini-2.5-flash")
        
        # Default headers for OpenRouter
        self.default_headers = {
            "HTTP-Referer": os.getenv("APP_URL", "http://localhost:8000"),
            "X-Title": "AI Data Agent"
        }

    def _get_client(self, model: Optional[str] = None, temperature: float = 0, **kwargs) -> ChatOpenAI:
        """
        Get a configured ChatOpenAI client for OpenRouter
        
        Args:
            model: Model ID to use (e.g., 'google/gemini-2.5-flash')
            temperature: Sampling temperature
            **kwargs: Additional arguments
            
        Returns:
            Configured ChatOpenAI client
        """
        if not self.api_key:
            raise ValueError("OPEN_ROUTER_KEY must be set")
            
        model_name = model or self.default_model
        
        return ChatOpenAI(
            model=model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=temperature,
            default_headers=self.default_headers,
            **kwargs
        )

    def _convert_messages(self, messages: List[Dict[str, str]]) -> List[BaseMessage]:
        """Convert dict messages to LangChain messages"""
        lc_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
            else:
                # Default to human for unknown roles
                lc_messages.append(HumanMessage(content=content))
        return lc_messages

    def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        max_tokens: int = 2000,
        model: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Generate text response from messages
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            model: Optional model override
            **kwargs: Additional parameters
        
        Returns:
            Generated text response
        """
        client = self._get_client(model=model, temperature=temperature, max_tokens=max_tokens, **kwargs)
        lc_messages = self._convert_messages(messages)
        
        response = client.invoke(lc_messages)
        return str(response.content)
    
    def generate_structured(
        self,
        messages: List[Dict[str, str]],
        response_format: Dict[str, Any],
        temperature: float = 0,
        model: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate structured JSON response
        
        Args:
            messages: List of message dicts
            response_format: JSON schema for structured output
            temperature: Sampling temperature
            model: Optional model override
            **kwargs: Additional parameters
        
        Returns:
            Parsed JSON response
        """
        client = self._get_client(model=model, temperature=temperature, **kwargs)
        lc_messages = self._convert_messages(messages)
        
        # Use with_structured_output if available and supported by the model/provider
        # OpenRouter supports response_format={"type": "json_object"} for some models
        # But standard LangChain generic usage with ChatOpenAI often relies on tool calling or json mode
        
        # We'll try using the structured output capability of LangChain which handles different providers
        try:
            structured_llm = client.with_structured_output(response_format)
            return structured_llm.invoke(lc_messages)
        except Exception:
            # Fallback: Force JSON mode via standard generation prompt/parameters
            # This is safer for models that might not support tool calling perfectly via OpenRouter mapping
            
            # Append schema instruction if not relying on native tool/struct support
            # (Though ChatOpenAI client might handle this, let's be explicit for generic models)
            
            # Note: with_structured_output usually works best. If it fails, we can try standard generation with JSON mode.
             
            client_json = self._get_client(
                model=model, 
                temperature=temperature, 
                model_kwargs={"response_format": {"type": "json_object"}},
                **kwargs
            )
            
            # Ensure the last message asks for JSON if not implicit
            # But usually the system prompt or user prompt should handle it.
            # Let's rely on the generic generate with JSON parsing as ultimate fallback
            response = client_json.invoke(lc_messages)
            content = str(response.content)
            
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                # Try to find JSON block
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                return json.loads(content)

    def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0,
        max_tokens: int = 2000,
        model: Optional[str] = None,
        **kwargs
    ) -> Iterator[str]:
        """
        Stream text response token by token
        
        Args:
            messages: List of message dicts
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            model: Optional model override
            **kwargs: Additional parameters
        
        Yields:
            Text chunks as they are generated
        """
        client = self._get_client(model=model, temperature=temperature, max_tokens=max_tokens, **kwargs)
        lc_messages = self._convert_messages(messages)
        
        for chunk in client.stream(lc_messages):
            if chunk.content:
                yield str(chunk.content)
