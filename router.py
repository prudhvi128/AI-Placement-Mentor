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
    """Classify a prompt into fast/medium/high model tier based on keyword analysis. Returns (model_name, complexity, reason)."""
    prompt_lower = prompt.lower()

    high_keywords = [
        "python", "java", "javascript", "typescript", "react", "angular", "vue",
        "c++", "c#", "golang", "rust", "swift", "kotlin", "ruby", "php",
        "html", "css", "sql", "nosql", "mongodb", "postgresql", "mysql",
        "docker", "kubernetes", "aws", "azure", "gcp", "terraform",
        "debug", "debugging", "compiler", "stack trace", "error",
        "algorithm", "data structure", "architecture", "design pattern",
        "refactor", "refactoring", "optimize", "optimization",
        "code review", "pull request", "ci/cd", "pipeline",
        "api", "rest", "graphql", "microservice", "microservices",
        "multithreading", "concurrency", "parallelism",
        "oop", "solid", "dependency injection",
        "machine learning", "deep learning", "neural network",
        "blockchain", "smart contract", "solidity",
        "devops", "sre", "observability", "monitoring",
        "testing", "unit test", "integration test", "e2e",
        "security", "authentication", "authorization", "oauth",
        "performance", "scalability", "load balancing",
        "code", "programming", "software engineering", "system design",
    ]

    medium_keywords = [
        "career", "resume", "interview", "job", "salary",
        "roadmap", "learning path", "certification",
        "skill", "portfolio", "linkedin", "github",
        "recommend", "suggest", "advice", "guide",
        "project", "assignment", "homework",
        "explain", "describe", "what is", "how to",
        "compare", "difference between", "pros and cons",
    ]

    for kw in high_keywords:
        if kw in prompt_lower:
            return HIGH_MODEL, "high", f"Prompt contains technical keyword: '{kw}'"

    for kw in medium_keywords:
        if kw in prompt_lower:
            return MEDIUM_MODEL, "medium", f"Prompt contains career/educational keyword: '{kw}'"

    if len(prompt) > 200:
        return MEDIUM_MODEL, "medium", "Long prompt (>200 chars) requires moderate capability"

    if len(prompt) < 30:
        return FAST_MODEL, "low", "Short/simple prompt (<30 chars)"

    return FAST_MODEL, "low", "General query routed to fast model"


def estimate_cost(model, prompt_tokens, completion_tokens):
    """Estimate the API cost in USD for a given model and token counts."""
    if model == FAST_MODEL:
        return (prompt_tokens * FAST_INPUT_PRICE + completion_tokens * FAST_OUTPUT_PRICE) / 1_000_000
    if model == MEDIUM_MODEL:
        return (prompt_tokens * MEDIUM_INPUT_PRICE + completion_tokens * MEDIUM_OUTPUT_PRICE) / 1_000_000
    if model == HIGH_MODEL:
        return (prompt_tokens * HIGH_INPUT_PRICE + completion_tokens * HIGH_OUTPUT_PRICE) / 1_000_000
    return 0.0
