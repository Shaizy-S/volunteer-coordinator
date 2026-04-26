from datetime import datetime, timezone


URGENCY_WEIGHTS = {
    "critical": 40,
    "high": 30,
    "medium": 20,
    "low": 10
}

def compute_priority_score(need: dict) -> float:
    """
    Priority Score (0-100) based on:
    - Urgency (40%)
    - People affected (25%)
    - Time unaddressed (20%)
    - Resource gap / unassigned (15%)
    """
    # --- Urgency Score (0-40) ---
    urgency = need.get("urgency", "low").lower()
    urgency_score = URGENCY_WEIGHTS.get(urgency, 10)

    # --- People Affected Score (0-25) ---
    people = int(need.get("people_affected", 50))
    if people >= 1000:
        people_score = 25
    elif people >= 500:
        people_score = 20
    elif people >= 100:
        people_score = 15
    elif people >= 50:
        people_score = 10
    else:
        people_score = 5

    # --- Time Sensitivity Score (0-20) ---
    # Older unresolved needs score higher
    timestamp_str = need.get("timestamp", "")
    time_score = 10  # default
    if timestamp_str:
        try:
            submitted = datetime.fromisoformat(timestamp_str)
            # Make submitted timezone-aware if it isn't
            if submitted.tzinfo is None:
                submitted = submitted.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_old = (now - submitted).total_seconds() / 3600
            if hours_old >= 72:
                time_score = 20
            elif hours_old >= 24:
                time_score = 15
            elif hours_old >= 6:
                time_score = 10
            else:
                time_score = 5
        except Exception:
            time_score = 10

    # --- Resource Gap Score (0-15) ---
    status = need.get("status", "pending").lower()
    if status == "pending":
        resource_score = 15  # Fully unserved
    elif status == "partial":
        resource_score = 8
    else:
        resource_score = 0  # Already assigned/completed

    total = urgency_score + people_score + time_score + resource_score
    return round(total, 2)


def score_all_needs(needs: list) -> list:
    """Add priority_score to each need and return sorted list."""
    scored = []
    for need in needs:
        score = compute_priority_score(need)
        need_copy = dict(need)
        need_copy["priority_score"] = score
        scored.append(need_copy)
    # Sort highest score first
    scored.sort(key=lambda x: x["priority_score"], reverse=True)
    return scored