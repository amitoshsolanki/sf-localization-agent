import os


def get_chat_model(node_name: str | None = None):
    """Return a LangChain chat model based on env config.

    Checks for per-node overrides first (e.g. TRANSLATOR_LLM_PROVIDER),
    then falls back to global LLM_PROVIDER / LLM_MODEL.
    """
    prefix = node_name.upper() if node_name else None

    provider = (
        os.getenv(f"{prefix}_LLM_PROVIDER") if prefix else None
    ) or os.getenv("LLM_PROVIDER", "gemini")

    model = (
        os.getenv(f"{prefix}_LLM_MODEL") if prefix else None
    ) or os.getenv("LLM_MODEL", "gemini-2.0-flash")

    provider = provider.lower()

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model)

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model)

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        kwargs = {"model": model}
        base_url = os.getenv("OPENAI_API_BASE")
        if base_url:
            kwargs["base_url"] = base_url
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            kwargs["api_key"] = api_key
        return ChatOpenAI(**kwargs)

    raise ValueError(
        f"Unknown LLM provider '{provider}'. "
        f"Supported: gemini, anthropic, ollama, openai"
    )
