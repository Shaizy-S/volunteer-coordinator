import math
from gemini_parser import get_batch_skill_relevance, keyword_relevance


def haversine_distance(lat1, lng1, lat2, lng2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def proximity_score(distance_km: float) -> float:
    if distance_km <= 5:   return 30
    elif distance_km <= 15: return 22
    elif distance_km <= 30: return 14
    elif distance_km <= 60: return 7
    else:                   return 2


def availability_score(volunteer: dict) -> float:
    assigned = int(volunteer.get("assigned_count", 0))
    availability = str(volunteer.get("availability", "available")).lower()
    if availability != "available": return 0
    if assigned == 0:  return 20
    elif assigned == 1: return 15
    elif assigned == 2: return 8
    else:              return 0


def find_top_matches(need: dict, volunteers: list, top_n: int = 3, use_gemini: bool = True) -> list:
    """
    One batch Gemini call for all volunteers → huge quota saving.
    Old approach: 8 volunteers = 8 Gemini calls
    New approach: 8 volunteers = 1 Gemini call
    """
    # Filter out unavailable volunteers first
    available = [v for v in volunteers if availability_score(v) > 0]

    if not available:
        return []

    # Get skill scores — ONE Gemini call for all volunteers
    if use_gemini:
        batch_results = get_batch_skill_relevance(need, available)
        # Build lookup by volunteer id
        skill_lookup = {
            str(r.get("id")): r for r in batch_results
        }
    else:
        skill_lookup = {}

    scores = []
    for vol in available:
        avail = availability_score(vol)

        # Proximity
        try:
            need_lat = float(need.get("lat") or 0)
            need_lng = float(need.get("lng") or 0)
            vol_lat = float(vol.get("lat") or 0)
            vol_lng = float(vol.get("lng") or 0)
            if 0 in [need_lat, need_lng, vol_lat, vol_lng]:
                prox = 10
                distance_km = -1
            else:
                dist = haversine_distance(need_lat, need_lng, vol_lat, vol_lng)
                prox = proximity_score(dist) if math.isfinite(dist) else 10
                distance_km = round(dist, 1) if math.isfinite(dist) else -1
        except Exception:
            prox = 10
            distance_km = -1

        # Skill score
        if use_gemini:
            vol_id = str(vol.get("id", ""))
            match_data = skill_lookup.get(vol_id, {})
            skill_raw = float(match_data.get("relevance_score", 5))
            skill_reason = match_data.get("reason", "")
        else:
            kw = keyword_relevance(
                need.get("description", ""),
                need.get("category", ""),
                vol.get("skills", "")
            )
            skill_raw = float(kw.get("relevance_score", 5))
            skill_reason = kw.get("reason", "keyword match")

        skill_score = (skill_raw / 10) * 50
        total = round(skill_score + prox + avail, 2)
        if not math.isfinite(total):
            total = 0.0

        scores.append({
            "volunteer_id": str(vol.get("id", "")),
            "name": vol.get("name", ""),
            "skills": vol.get("skills", ""),
            "location": vol.get("location", ""),
            "distance_km": distance_km,
            "match_score": total,
            "skill_relevance": round(skill_raw, 1),
            "skill_reason": skill_reason,
            "assigned_count": int(vol.get("assigned_count", 0))
        })

    scores.sort(key=lambda x: x["match_score"], reverse=True)
    return scores[:top_n]


def run_matching_for_all_needs(needs: list, volunteers: list, use_gemini: bool = True) -> list:
    results = []
    active = [n for n in needs if n.get("status", "pending") != "completed"]
    active.sort(key=lambda x: float(x.get("priority_score", 0)), reverse=True)

    for need in active:
        matches = find_top_matches(need, volunteers, top_n=3, use_gemini=use_gemini)
        results.append({"need": need, "top_matches": matches})

    return results