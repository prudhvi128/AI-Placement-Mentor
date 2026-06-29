"""User-scoped persistent memory — Supabase-backed key-value store per user_id.
Replaces the previous Hindsight-based global memory with authenticated-user scoping.
"""

# -----------------------------
# Generic Functions
# -----------------------------

def save_memory(user_id: str, content: str, key: str | None = None) -> bool:
    """Save a text entry to the user's persistent memory.
    If key is None, a default key like 'memory_{timestamp}' is used.
    """
    import database
    import uuid
    k = key or f"memory_{uuid.uuid4().hex[:8]}"
    return database.upsert_user_memory(user_id, k, content)


def search_memory(user_id: str) -> str:
    """Return all persistent memory entries for the given user as formatted text."""
    import database
    rows = database.get_user_memory(user_id)
    if not rows:
        return ""
    lines = []
    for r in rows:
        k = r.get("key", "")
        v = r.get("value", "")
        label = k.replace("_", " ").title()
        lines.append(f"- {label}: {v}")
    return "\n".join(lines)


# -----------------------------
# Structured Memory Functions
# -----------------------------
import database
def save_career_goal(user_id: str, goal: str) -> bool:
    """Store a user career goal in persistent memory."""
    return database.upsert_user_memory(user_id, "career_goal", goal.strip())


def save_learning_progress(user_id: str, progress: str) -> bool:
    """Store learning progress update in persistent memory."""
    return database.upsert_user_memory(user_id, "learning_progress", progress.strip())


def save_resume_analysis(user_id: str, analysis: str) -> bool:
    """Store a summary of resume analysis in persistent memory (truncated to 600 chars)."""
    summary = analysis.strip()[:600]
    return database.upsert_user_memory(user_id, "resume_analysis_summary", summary)


def save_ats_score(user_id: str, score: str) -> bool:
    """Store ATS score line in persistent memory."""
    return database.upsert_user_memory(user_id, "ats_score", score.strip())


def save_missing_skills(user_id: str, skills: str) -> bool:
    """Store missing skills data in persistent memory."""
    return database.upsert_user_memory(user_id, "missing_skills", skills.strip())


def save_interview_report(user_id: str, report: str) -> bool:
    """Store a summary of the latest interview report in persistent memory
    (truncated to 600 chars). Overwrites the previous entry.
    """
    summary = report.strip()[:600]
    return database.upsert_user_memory(user_id, "interview_report_summary", summary)


# -----------------------------
# Personal Info Extraction
# -----------------------------

def extract_and_save_user_info(user_id: str, text: str) -> None:
    """Extract personal information (name, location, job, etc.) from user text
    and save to persistent memory. Uses regex patterns to detect self-introductions.
    """
    import re
    patterns = {
        "user_name": [
            r"(?:my name is|my name's)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"call me\s+([A-Z][a-z]+)",
        ],
        "user_location": [
            r"(?:i live in|i'm from|i am from|based in)\s+([A-Za-z\s]+?)(?:,|\.|!|\?|$)",
        ],
        "user_job_role": [
            r"(?:i work as|i'm a|i am a)\s+(?:an?\s+)?([A-Za-z\s]+?)\s+(?:at|for|in|with|and|\.|,|!|\?)",
        ],
        "user_company": [
            r"(?:i work at|i work for)\s+([A-Za-z0-9\s]+?)(?:,|\.|!|\?|$)",
        ],
    }

    for key, regexes in patterns.items():
        for pattern in regexes:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                value = m.group(1).strip().rstrip(".,!?")
                if len(value) > 2 and len(value) < 100:
                    database.upsert_user_memory(user_id, key, value)
                    print(f"[MEMORY] Saved {key} = {value}")
                    break


# -----------------------------
# Interview Context Builder (unchanged — reads from Supabase tables directly)
# -----------------------------

def build_interview_memory_context(user_id: str) -> str:
    """Build a text summary of past interview performance and persistent weaknesses for AI context."""
    try:
        import database
        reports = database.get_interview_reports(user_id)
        weaknesses = database.get_user_weaknesses(user_id)
    except Exception:
        return ""

    lines = []
    if reports:
        lines.append("=== PAST INTERVIEW PERFORMANCE ===")
        for i, r in enumerate(reports[:3], 1):
            score = r.get("overall_score", "?")
            tech = r.get("technical_score", "?")
            comm = r.get("communication_score", "?")
            conf = r.get("confidence_score", "?")
            weak = (r.get("weaknesses") or "")[:200]
            lines.append(f"Interview {i}: Overall={score}/10, Tech={tech}/10, Comm={comm}/10, Conf={conf}/10")
            if weak:
                lines.append(f"  Weaknesses: {weak}")

    active_weak = [w for w in weaknesses if w["status"] in ("active", "improving")]
    if active_weak:
        lines.append("")
        lines.append("=== PERSISTENT WEAKNESSES TO REVISIT ===")
        for w in active_weak:
            lines.append(f"- {w['weakness_text']} (detected {w.get('detected_count', 1)}x)")

    if lines:
        lines.append("")
        lines.append("---")
        lines.append("Use this context to tailor questions toward previously weak areas and track improvement.")

    return "\n".join(lines)
