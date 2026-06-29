
"""AI provider layer â€” CascadeFlow routing with Groq backend, warmup, response sanitization."""

import time
import asyncio
import streamlit as st
import requests
from dotenv import load_dotenv
from cascadeflow import (
    CascadeAgent,
    ModelConfig,
)

load_dotenv()

_CASCADE_LOOP = None

# Reusable ModelConfigs keyed by model name (used by update_models).
_MODEL_CONFIGS = {
    "llama-3.1-8b-instant": ModelConfig(
        name="llama-3.1-8b-instant", provider="groq",
        cost=0.00003, cost_output=0.00008,
    ),
    "llama-3.3-70b-versatile": ModelConfig(
        name="llama-3.3-70b-versatile", provider="groq",
        cost=0.00059, cost_output=0.00079,
    ),
    "qwen/qwen3-32b": ModelConfig(
        name="qwen/qwen3-32b", provider="groq",
        cost=0.00079, cost_output=0.00099,
    ),
}


def warmup_ai() -> bool:
    """Warm up by making a minimal Groq API call directly.
    Eliminates fragile CascadeFlow / asyncio event-loop management.
    Logs every step to the terminal and stores errors in session state.
    """
    if st.session_state.get("ai_ready", False):
        print("[AI] Already ready, skipping warmup.")
        return True

    print("[AI] === WARMUP START ===")

    from config import GROQ_API_KEY
    api_key = GROQ_API_KEY

    if not api_key:
        msg = "GROQ_API_KEY is not set. Check your .env file."
        print(f"[AI] FAIL: {msg}")
        st.session_state._ai_error = msg
        return False

    print(f"[AI] API key loaded (len={len(api_key)})")

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0.1,
    }

    last_error = ""
    for attempt in range(3):
        try:
            print(f"[AI] Warmup attempt {attempt + 1}/3 ...")
            start = time.time()
            resp = requests.post(url, headers=headers, json=data, timeout=10)
            elapsed = time.time() - start
            print(f"[AI] HTTP {resp.status_code} in {elapsed:.2f}s")

            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}: {resp.text[:300]}")

            result = resp.json()
            if "choices" not in result:
                raise Exception(f"Unexpected response: {result}")

            print(f"[AI] Warmup SUCCESS (attempt {attempt + 1})")
            st.session_state.ai_ready = True
            st.session_state.pop("_ai_error", None)
            print("[AI] === WARMUP COMPLETE ===")
            return True

        except requests.exceptions.Timeout:
            last_error = f"Request timed out (10s)"
            print(f"[AI] Attempt {attempt + 1}: {last_error}")
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {e}"
            print(f"[AI] Attempt {attempt + 1}: {last_error}")
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            print(f"[AI] Attempt {attempt + 1}: {last_error}")

        if attempt < 2:
            backoff = 2 ** attempt  # 1s, 2s, 4s
            print(f"[AI] Retrying in {backoff}s ...")
            time.sleep(backoff)

    print(f"[AI] === WARMUP FAILED after 3 attempts ===")
    print(f"[AI] Last error: {last_error}")
    st.session_state._ai_error = last_error
    return False


def is_ready() -> bool:
    return st.session_state.get("ai_ready", False)


def get_warmup_error() -> str:
    return st.session_state.get("_ai_error", "")


# =============================================================================
# CASCADEFLOW INITIALIZATION
# =============================================================================

def _init_cascade_agent():
    """Initialize CascadeFlow agent with Groq models for routing only.

    Cascade is DISABLED — only one model is used per request (no draft/verifier).
    CascadeFlow is used solely for complexity detection and to provide
    the metadata format consumed by the UI metadata bar.
    Model selection is handled by router.route_model().
    """
    if "_cascade_agent" in st.session_state:
        return st.session_state._cascade_agent

    from config import GROQ_API_KEY

    # Define models in cost order (cheapest to most expensive)
    models = [
        ModelConfig(
            name="llama-3.1-8b-instant",
            provider="groq",
            cost=0.00003,
            cost_output=0.00008,
        ),
        ModelConfig(
            name="llama-3.3-70b-versatile",
            provider="groq",
            cost=0.00059,
            cost_output=0.00079,
        ),
        ModelConfig(
            name="qwen/qwen3-32b",
            provider="groq",
            cost=0.00079,
            cost_output=0.00099,
        ),
    ]

    # Cascade disabled — the agent is only used for complexity detection
    # and its PreRouter always returns DIRECT_BEST (single model).
    agent = CascadeAgent(
        models=models,
        enable_cascade=False,
        verbose=False,
    )

    st.session_state._cascade_agent = agent
    print("[AI] CascadeFlow agent initialized (cascade disabled — routing only)")
    return agent


def _get_cascade_loop():
    """Return a Streamlit-safe asyncio event loop for CascadeFlow execution."""
    global _CASCADE_LOOP
    loop = _CASCADE_LOOP
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _CASCADE_LOOP = loop
        st.session_state.pop("_cascade_agent", None)
    asyncio.set_event_loop(loop)
    return loop


def _run_cascade(agent, **kwargs):
    """Run CascadeAgent.run() inside a persistent event loop (Streamlit-safe)."""
    loop = _get_cascade_loop()
    if loop.is_running():
        raise RuntimeError("CascadeFlow event loop is already running")
    return loop.run_until_complete(agent.run(**kwargs))


def _current_prompt_complexity_hint(agent, prompt: str) -> str | None:
    """Use CascadeFlow's detector on the latest user turn, not the whole system prompt."""
    try:
        detected = agent.complexity_detector.detect(prompt)
        complexity = detected[0]
        return getattr(complexity, "value", str(complexity))
    except Exception:
        return None


# =============================================================================
# MEMORY CONTEXT BUILDER
# =============================================================================

from memory import (
    search_memory,
    save_career_goal,
    save_learning_progress,
    save_resume_analysis,
    save_ats_score,
    save_missing_skills,
    save_interview_report,
    build_interview_memory_context,
    extract_and_save_user_info,
)
from config import GROQ_API_KEY
import database


def _strip_reasoning(text: str) -> str:
    """Remove reasoning/thinking/planning sections from model responses.
    Strips known tag formats, preamble sentences, and self-talk patterns.
    """
    import re

    # â”€â”€ 1. XML/HTML reasoning blocks â”€â”€
    # Match common reasoning tags: <think>, <reasoning>, <thinking>, etc.
    # Process line by line to handle unclosed tags
    lines = text.split('\n')
    cleaned_lines = []
    skip_until_closing = False

    for line in lines:
        line_stripped = line.strip()
        # Check if line starts with a reasoning tag
        if re.match(r'<(think|thinking|thought|reasoning|analysis|plan)>', line_stripped, re.IGNORECASE):
            skip_until_closing = True
            continue
        # Check if line has a closing tag
        if re.search(r'</(think|thinking|thought|reasoning|analysis|plan)>', line_stripped, re.IGNORECASE):
            skip_until_closing = False
            continue
        # Skip lines if we're inside a reasoning block
        if skip_until_closing:
            continue
        cleaned_lines.append(line)

    text = '\n'.join(cleaned_lines)

    # â”€â”€ 2. BBcode reasoning blocks â”€â”€
    text = re.sub(
        r'\[(?:thinking|thought|reasoning|analysis|plan)\].*?\[/(?:thinking|thought|reasoning|analysis|plan)\]',
        '', text, flags=re.DOTALL | re.IGNORECASE
    )

    # â”€â”€ 3. Fenced reasoning blocks (```thinking ... ```) â”€â”€
    text = re.sub(
        r'```(?:thinking|thought|reasoning|analysis|plan)\s*\n.*?```',
        '', text, flags=re.DOTALL | re.IGNORECASE
    )

    # â”€â”€ 4. Markdown-formatted reasoning markers through blank line â”€â”€
    # Strip **Thinking:** / **Thought:** / **Reasoning:** / **Analysis:** markers.
    # For headings (##), only strip thinking/thought/reasoning â€” NOT "analysis"
    # (which is often a legitimate answer section header).
    text = re.sub(
        r'(?:\*{1,2}(?:thinking|thought|reasoning|analysis)\*{0,2}:|'
        r'#{1,6}\s*(?:thinking|thought|reasoning)).*?(?:\n\n|$)',
        '', text, flags=re.DOTALL | re.IGNORECASE
    )

    # â”€â”€ 5. Preamble reasoning sentences at start of text â”€â”€
    # Each pattern matches a SINGLE sentence that begins with self-talk / planning.
    # Uses [^.!?\n]*[.!?\n]? to match exactly one sentence (not everything to end-of-line),
    # so answer content on the same line survives.
    _S = r'(?:[^.!?\n]*[.!?\n]?)?'  # match one sentence (optional content + optional ending)
    preambles = [
        # "Let me think/analyze/consider/check..."
        rf'^let me (?:think|reason|analyze|consider|check|verify|review|examine|assess|evaluate|determine|figure|plan|prepare|look|see|explain|elaborate|start|begin)\b{_S}',
        # "I need to check/verify/look..."
        rf'^i need to (?:check|verify|look|analyze|consider|understand|review|examine|assess|evaluate|determine|figure|think|reason|plan)\b{_S}',
        # "I should/will/must/can/want (also/just) [any verb]..." â€” catch ALL self-talk verbs
        rf"^i (?:should|'?ll|need to|want to|have to|must|can)\s+(?:also|then|now|first|just)?\s*\w+{_S}",
        # "I think/believe/feel/suppose/assume/guess/wonder..."
        rf'^i (?:think|believe|feel|suppose|assume|guess|wonder|imagine)\b{_S}',
        # "Before we proceed/continue/move/go..."
        rf'^before we (?:proceed|continue|move|go|answer|respond|dive|jump)\b{_S}',
        # "From previous/prior conversation/chat/message/context..."
        rf'^from (?:previous|prior) (?:conversation|chat|message|context|history)\b{_S}',
        # "First, let me / I'll / I need to / I should / I will / I want to..."
        rf"^first,? (?:let me|i'?ll|i need to|i should|i will|i want to)\b{_S}",
        # "Okay / So / Now / Well / Actually, the / let me / this / that / here / what / I / you / we / first / next..."
        rf"^(?:okay|so|now|well|actually),?\s+(?:the|this|that|let me|here|what|i|you|we|first|next)\b{_S}",
        # "Alright, let me / I'll..."
        rf"^alright,?\s*(?:let me|i'?ll)\b{_S}",
        # "The user is/wants/asked/needs/has/would like/is asking..."
        rf'^the user (?:is|wants|asked|needs|has|would like|is asking)\b{_S}',
        # "To answer/address/respond to this/the/your/that..."
        rf'^to (?:answer|address|respond to) (?:this|the|your|that)\b{_S}',
        # "As an AI/assistant/LLM..."
        rf'^as an (?:ai|assistant|llm)\b{_S}',
        # "Next, let me / I'll / explain / describe / mention / note / say / we..."
        rf"^next,?\s+(?:let me|i'?ll|i|explain|describe|mention|note|say|we)\b{_S}",
        # "Check if/whether/the/for/your/user/their..."
        rf'^check\s+(?:if|whether|the|for|your|user|their)\b{_S}',
        # "Wait... / Wait, let me / Wait, I..."
        rf'^wait,?\s*(?:let me|i|the|\.\.\.)?{_S}',
        # "Here's my/the/what/how..."
        rf"^here's (?:my|the|what|how)\b{_S}",
    ]

    while True:
        matched = False
        for pat in preambles:
            m = re.match(pat, text, re.IGNORECASE)
            if m:
                text = text[m.end():].lstrip()
                matched = True
                break  # restart scanning from the first pattern
        if not matched:
            break

    # â”€â”€ 6. Strip memory-update / system announcements (silent memory) â”€â”€
    text = re.sub(
        r'(?im)^(?:âœ…\s*)?'
        r'(?:'
        r'no\s+(?:information|data|context|memory|entries)(?:\s+\w+){0,5}\s+(?:exists|found|available|stored)|'
        r'nothing\s+(?:in|found|stored)\s+(?:memory|context)|'
        r'(?:retrieved|fetched|loaded|gathered|found|collected)(?:\s+\w+){0,6}\s+(?:memory|memories|context|information|data)|'
        r'(?:searching|checking|consulting|querying|looking\s+up|accessing|reading)\s+(?:memory|memories|context|storage)|'
        r'(?:memory|memories|context)\b.{0,20}?(?:updated|saved|stored|recorded|found|retrieved|checked|searched|accessed|queried)|'
        r'(?:saved|stored|written|updated|added)(?:\s+\w+){0,3}\s+(?:to|in)\s+(?:memory|memories|context)|'
        r'updated\s+(?:user|name|memory|goal|preference|skill|profile|detail|info)|'
        r'added\s+to\s+(?:long[-\s]term\s+)?(?:[\w-]+\s+)*?memory\b'
        r').*?(?:\n|$)',
        '', text
    )

    # â”€â”€ 7. Remove leftover double spacing â”€â”€
    # Strip leading markdown headings from response start
    text = re.sub(
        r'^(?:#{1,6}\s+.*?(?:\n|$)(?:---+\n)?)+',
        '', text
    )

    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def sanitize_messages_for_groq(messages):
    """Strip every field except 'role' and 'content' for Groq API compatibility."""
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def _build_user_context(user_id: str) -> str:
    """Build a comprehensive context string from all persistent user data sources.
    Includes: user_memory entries, interview reports, weaknesses, roadmaps, and career recommendations.
    """
    parts = []

    # 1. User memory (career goals, learning progress, resume summary, etc.)
    mem_rows = database.get_user_memory(user_id)
    if mem_rows:
        lines = ["=== PERSISTENT USER MEMORY ==="]
        for r in mem_rows:
            k = r.get("key", "")
            v = r.get("value", "")
            label = k.replace("_", " ").title()
            lines.append(f"- {label}: {v}")
        parts.append("\n".join(lines))

    # 2. Interview performance (latest 3)
    reports = database.get_interview_reports(user_id)
    if reports:
        lines = ["=== PAST INTERVIEW PERFORMANCE ==="]
        for i, r in enumerate(reports[:3], 1):
            score = r.get("overall_score", "?")
            tech = r.get("technical_score", "?")
            comm = r.get("communication_score", "?")
            conf = r.get("confidence_score", "?")
            weak = (r.get("weaknesses") or "")[:200]
            lines.append(f"Interview {i}: Overall={score}/10, Tech={tech}/10, Comm={comm}/10, Conf={conf}/10")
            if weak:
                lines.append(f"  Weaknesses: {weak}")
        parts.append("\n".join(lines))

    # 3. Tracked weaknesses
    weaknesses = database.get_user_weaknesses(user_id)
    active = [w for w in weaknesses if w["status"] in ("active", "improving")]
    if active:
        lines = ["=== TRACKED WEAKNESSES ==="]
        for w in active:
            lines.append(f"- {w['weakness_text']} ({w['status']}, detected {w.get('detected_count', 1)}x)")
        parts.append("\n".join(lines))

    # 4. Latest learning roadmap
    roadmaps = database.get_learning_roadmaps(user_id)
    if roadmaps:
        latest = roadmaps[0].get("roadmap_markdown", "")
        parts.append(f"=== LATEST LEARNING ROADMAP (summary) ===\n{latest[:500]}")

    # 5. Latest career recommendation
    careers = database.get_career_recommendations(user_id)
    if careers:
        latest = careers[0].get("recommendation_markdown", "")
        parts.append(f"=== LATEST CAREER RECOMMENDATION ===\n{latest[:500]}")

    return "\n\n".join(parts)


# =============================================================================
# MAIN AI FUNCTIONS
# =============================================================================

def ask_ai(prompt, user_id: str = ""):
    """Send a chat prompt via CascadeFlow with single-model routing; return (answer, info_dict).

    CascadeFlow receives every request and executes it with exactly ONE model
    (no draft/verifier).  Model selection is done by router.route_model() and
    the agent's model list is narrowed to the selected model before each call.

    Returns:
        tuple: (answer_text, metadata_dict)
        metadata_dict contains all CascadeResult fields consumed by the UI.
    """
    from router import route_model

    agent = _init_cascade_agent()

    memory_context = _build_user_context(user_id) if user_id else ""

    system_prompt = f"""
You are an AI Placement Mentor.

Respond directly to the user's message.
Do not include internal reasoning, thinking, analysis, or planning.
Never explain your thought process.
Output only the final answer.
Never mention memory, stored information, context, or conversation history.

=== HOW TO USE THE CONTEXT BELOW ===
The section below labeled === USER CONTEXT === contains stored information about the user (past interview performance, weaknesses, resume analysis, learning roadmap, career goals, etc.).

RULES:
1. Use stored context SILENTLY to improve and personalize your answers.
2. For greetings, casual conversation, or simple questions, IGNORE stored context entirely. Do not reference past interviews, weaknesses, or profile data unless the user explicitly asks.
3. Only reference stored information when the user's current question is directly about that topic (e.g., asks about their name, personal info, interview prep, weaknesses, career path, skills, or roadmap).
4. Never list, summarize, or announce what you remember from past interactions.
5. Answer the user's CURRENT message first. Do not lead with a recap of their history.
6. Never use phrases like "based on your profile", "according to your memory", "your past interviews show", or "I remember you...". Incorporate relevant context naturally as if it is your own knowledge.
7. If no part of the stored context is relevant to the current question, proceed normally as if you have no stored information.

Format your response in Markdown.
Do not use headings (##, ###, etc.) — respond directly with plain text or bullet points.
Wrap code inside triple backticks.
Explain code after it.
Mention time and space complexity for coding questions."""

    if "resume_text" in st.session_state:
        system_prompt += f"""

The user has uploaded the following resume:

{st.session_state['resume_text']}

Use this resume whenever the user asks about:
- Resume
- Skills
- Career
- Jobs
- Interview questions
- Learning roadmap
- ATS score
"""

    context_section = ""
    if memory_context:
        context_section = f"""

=== USER CONTEXT ===

{memory_context}"""

    messages = [
        {
            "role": "system",
            "content": system_prompt + context_section
        }
    ] + sanitize_messages_for_groq(st.session_state.messages)

    start = time.time()
    try:
        complexity = _current_prompt_complexity_hint(agent, prompt) or "simple"

        selected_model, tier, route_reason = route_model(prompt)

        model_cfg = _MODEL_CONFIGS.get(selected_model)
        if model_cfg is None:
            raise ValueError(f"Unknown model: {selected_model}")
        agent.update_models([model_cfg])

        result = _run_cascade(
            agent,
            query=prompt,
            messages=messages,
            max_tokens=4096,
            temperature=0.7,
        )

        answer = _strip_reasoning(result.content)

        metadata = {
            "model": result.model_used,
            "latency": result.latency_ms,
            "cost": result.total_cost,
            "complexity": result.complexity,
            "routing_strategy": result.routing_strategy,
            "cascaded": result.cascaded,
            "draft_accepted": result.draft_accepted,
            "reason": f"routed to {tier}: {route_reason}",
            "quality_score": result.quality_score,
            "quality_threshold": result.quality_threshold,
            "quality_check_passed": result.quality_check_passed,
            "rejection_reason": result.rejection_reason,
            "draft_model": result.draft_model,
            "draft_latency_ms": result.draft_latency_ms,
            "draft_confidence": result.draft_confidence,
            "verifier_model": result.verifier_model,
            "verifier_latency_ms": result.verifier_latency_ms,
            "verifier_confidence": result.verifier_confidence,
            "draft_cost": result.draft_cost,
            "verifier_cost": result.verifier_cost,
            "cost_saved": result.cost_saved,
            "complexity_detection_ms": result.complexity_detection_ms,
            "draft_generation_ms": result.draft_generation_ms,
            "quality_verification_ms": result.quality_verification_ms,
            "verifier_generation_ms": result.verifier_generation_ms,
            "cascade_overhead_ms": result.cascade_overhead_ms,
            "metadata": result.metadata,
            "provider": "Groq",
        }

        st.session_state.ai_ready = True

    except Exception as e:
        return (
            f"âš ï¸ **AI request failed:** `{type(e).__name__}: {e}`",
            {
                "model": "unknown",
                "latency": 0,
                "cost": 0,
                "complexity": "unknown",
                "routing_strategy": "unknown",
                "cascaded": False,
                "reason": str(e),
            },
        )

    career_words = [
    "want to become",
    "my goal is",
    "career goal",
    "dream job"
    ]

    if user_id and any(word in prompt.lower() for word in career_words):
        save_career_goal(user_id, prompt)
    learning_words = [
    "completed",
    "finished",
    "learned",
    "studied"
    ]

    if user_id and any(word in prompt.lower() for word in learning_words):
        save_learning_progress(user_id, prompt)

    # Extract personal info (name, location, job, etc.) from user's message
    if user_id:
        extract_and_save_user_info(user_id, prompt)

    return (answer, metadata)


def analyze_resume(resume_text, user_id: str = ""):
    """Analyze a resume via Groq â€” ATS score, strengths/weaknesses, missing skills, suggested projects, interview questions, learning roadmap."""
    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""
You are an expert resume reviewer.

Analyze the following resume and provide:

1. ATS Score (out of 100)
2. Strengths
3. Weaknesses
4. Missing Skills
5. Suggested Projects
6. Interview Questions
7. Learning Roadmap

Resume:

{resume_text}
"""

    data = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    response = requests.post(url, headers=headers, json=data)

    result = response.json()

    if "choices" not in result:
        return f"Error: {result}"

    analysis = _strip_reasoning(result["choices"][0]["message"]["content"])

    if user_id:
        save_resume_analysis(user_id, analysis)

    # -----------------------
    # Save ATS Score
    # -----------------------

        for line in analysis.split("\n"):
            if "ATS" in line.upper():
                save_ats_score(user_id, line)
                break

    # -----------------------
    # Save Missing Skills
    # -----------------------

        if "Missing Skills" in analysis:
            section = analysis.split("Missing Skills")[-1]
            save_missing_skills(user_id, section[:500])

    return analysis
