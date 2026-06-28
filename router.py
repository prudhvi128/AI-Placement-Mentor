"""Model routing logic — keyword-based prompt classification into fast/medium/high tiers with pricing."""

FAST_MODEL = "llama-3.1-8b-instant"
MEDIUM_MODEL = "llama-3.3-70b-versatile"
HIGH_MODEL = "qwen/qwen3-32b"

FAST_INPUT_PRICE = 0.03
FAST_OUTPUT_PRICE = 0.08
MEDIUM_INPUT_PRICE = 0.59
MEDIUM_OUTPUT_PRICE = 0.79
HIGH_INPUT_PRICE = 0.79
HIGH_OUTPUT_PRICE = 0.99


def route_model(prompt):
    """Route prompts to Fast / Medium / High models using a simple scoring system."""

    prompt_lower = prompt.lower()
    score = 0
    reasons = []

    high_keywords = [
        "system design", "distributed system", "microservices",
        "kubernetes", "docker", "kafka", "redis", "sharding",
        "load balancer", "cap theorem", "raft", "paxos",
        "event sourcing", "cqrs", "vector database",
        "rag", "llm", "transformer", "gpu",
        "compiler", "kernel", "operating system internals",
    ]

    medium_keywords = [
        "python", "java", "javascript", "typescript",
        "react", "angular", "vue",
        "c++", "c#", "golang", "rust",
        "html", "css",
        "sql", "mongodb", "postgresql", "mysql",
        "oop", "solid",
        "algorithm", "data structure",
        "api", "rest", "graphql",
        "debug", "testing",
        "resume", "interview", "career",
        "project", "roadmap",
        "explain", "compare", "difference",
    ]

    for kw in high_keywords:
        if kw in prompt_lower:
            score += 4
            reasons.append(kw)

    for kw in medium_keywords:
        if kw in prompt_lower:
            score += 2
            reasons.append(kw)

    # Prompt length contributes to complexity
    if len(prompt) > 800:
        score += 6
    elif len(prompt) > 400:
        score += 4
    elif len(prompt) > 200:
        score += 2

    # Route based on total score
    if score >= 10:
        return HIGH_MODEL, "high", f"Score={score} ({', '.join(reasons[:3])})"

    elif score >= 4:
        return MEDIUM_MODEL, "medium", f"Score={score} ({', '.join(reasons[:3])})"

    else:
        return FAST_MODEL, "low", f"Score={score}"

def estimate_cost(model, prompt_tokens, completion_tokens):
    """Estimate the API cost in USD for a given model and token counts."""
    if model == FAST_MODEL:
        return (prompt_tokens * FAST_INPUT_PRICE + completion_tokens * FAST_OUTPUT_PRICE) / 1_000_000
    if model == MEDIUM_MODEL:
        return (prompt_tokens * MEDIUM_INPUT_PRICE + completion_tokens * MEDIUM_OUTPUT_PRICE) / 1_000_000
    if model == HIGH_MODEL:
        return (prompt_tokens * HIGH_INPUT_PRICE + completion_tokens * HIGH_OUTPUT_PRICE) / 1_000_000
    return 0.0
