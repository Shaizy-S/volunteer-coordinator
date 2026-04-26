from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os, uuid, math
from datetime import datetime, timezone

load_dotenv()

from sheets import (get_all_needs, add_need, update_need,
                    get_all_volunteers, add_volunteer, update_volunteer,
                    get_all_assignments, add_assignment, complete_assignment)
from gemini_parser import parse_need, generate_situation_summary
from scoring import compute_priority_score, score_all_needs
from matcher import run_matching_for_all_needs, find_top_matches

app = Flask(__name__)
CORS(app)


def sanitize(obj):
    if isinstance(obj, float):
        return 0 if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(i) for i in obj]
    return obj


# ── HEALTH ────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ── SUBMIT NEED ───────────────────────────────────────────────
@app.route("/api/needs", methods=["POST"])
def submit_need():
    body = request.get_json()
    description = body.get("description", "").strip()
    if not description:
        return jsonify({"error": "description is required"}), 400

    parse_result = parse_need(description)
    if not parse_result["success"]:
        return jsonify({"error": "Parsing failed", "details": parse_result}), 500

    parsed = parse_result["data"]
    need = {
        "id": str(uuid.uuid4())[:8],
        "ngo_name": body.get("ngo_name", ""),
        "contact": body.get("contact", ""),
        "description": description,
        "category": parsed.get("category", "other"),
        "urgency": parsed.get("urgency", "medium"),
        "people_affected": parsed.get("people_affected", 50),
        "location": parsed.get("location") or body.get("location", "Unknown"),
        "lat": float(body.get("lat", 0)),
        "lng": float(body.get("lng", 0)),
        "status": "pending",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "assigned_volunteer": ""
    }
    need["priority_score"] = compute_priority_score(need)
    add_need(need)

    return jsonify({
        "success": True,
        "need": need,
        "gemini_summary": parsed.get("summary", ""),
        "parsed_by": parse_result.get("source", "gemini")
    }), 201


# ── GET ALL NEEDS ─────────────────────────────────────────────
@app.route("/api/needs", methods=["GET"])
def get_needs():
    needs = get_all_needs()
    scored = score_all_needs(needs)
    return jsonify(sanitize({"needs": scored, "count": len(scored)}))


# ── REGISTER VOLUNTEER ────────────────────────────────────────
@app.route("/api/volunteers", methods=["POST"])
def register_volunteer():
    body = request.get_json()
    name = body.get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    vol = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "phone": body.get("phone", ""),
        "skills": body.get("skills", ""),
        "location": body.get("location", ""),
        "lat": float(body.get("lat", 0)),
        "lng": float(body.get("lng", 0)),
        "availability": body.get("availability", "available"),
        "assigned_count": 0,
        "max_capacity": int(body.get("max_capacity", 2))
    }
    add_volunteer(vol)
    return jsonify({"success": True, "volunteer": vol}), 201


# ── GET ALL VOLUNTEERS ────────────────────────────────────────
@app.route("/api/volunteers", methods=["GET"])
def get_volunteers():
    volunteers = get_all_volunteers()
    return jsonify(sanitize({"volunteers": volunteers, "count": len(volunteers)}))


# ── GET MATCHES ───────────────────────────────────────────────
@app.route("/api/matches", methods=["GET"])
def get_matches():
    use_gemini = request.args.get("use_gemini", "true").lower() == "true"
    needs = get_all_needs()
    volunteers = get_all_volunteers()
    scored = score_all_needs(needs)
    results = run_matching_for_all_needs(scored, volunteers, use_gemini=use_gemini)
    return jsonify(sanitize({
        "matches": results,
        "total_needs": len(needs),
        "total_volunteers": len(volunteers)
    }))


# ── CONFIRM ASSIGNMENT ────────────────────────────────────────
@app.route("/api/assign", methods=["POST"])
def confirm_assignment():
    """Coordinator confirms a match → updates need + volunteer in Sheets."""
    body = request.get_json()
    need_id = body.get("need_id")
    volunteer_id = body.get("volunteer_id")

    if not need_id or not volunteer_id:
        return jsonify({"error": "need_id and volunteer_id required"}), 400

    # Update need status
    update_need(need_id, {
        "status": "assigned",
        "assigned_volunteer": volunteer_id
    })

    # Increment volunteer assignment count
    volunteers = get_all_volunteers()
    vol = next((v for v in volunteers if str(v.get("id")) == str(volunteer_id)), None)
    if vol:
        new_count = int(vol.get("assigned_count", 0)) + 1
        update_volunteer(volunteer_id, {"assigned_count": new_count})

    # Log to Assignments sheet
    add_assignment(need_id, volunteer_id)

    return jsonify({"success": True, "need_id": need_id, "volunteer_id": volunteer_id})



# ── SUMMARY ───────────────────────────────────────────────────
@app.route("/api/summary", methods=["GET"])
def situation_summary():
    needs = get_all_needs()
    pending = [n for n in needs if n.get("status") != "completed"]
    scored = score_all_needs(pending)[:5]
    summary = generate_situation_summary(scored)
    return jsonify({"summary": summary, "needs_analyzed": len(scored)})


# ── BURNOUT ───────────────────────────────────────────────────
@app.route("/api/volunteers/burnout", methods=["GET"])
def burnout_alerts():
    volunteers = get_all_volunteers()
    overloaded, at_risk = [], []
    safe_count = 0

    for v in volunteers:
        count = int(v.get("assigned_count", 0))
        max_cap = int(v.get("max_capacity", 2))
        name = v.get("name", "Unknown")

        if count >= max_cap + 1:
            overloaded.append({
                "name": name,
                "assigned_count": count,
                "status": "overloaded",
                "message": f"{name} has {count} active assignments — excluded from new matches"
            })
        elif count >= max_cap:
            at_risk.append({
                "name": name,
                "assigned_count": count,
                "status": "at_risk",
                "message": f"{name} is at capacity ({count}/{max_cap} assignments)"
            })
        else:
            safe_count += 1

    return jsonify({
        "overloaded": overloaded,
        "at_risk": at_risk,
        "safe_count": safe_count,
        "total": len(volunteers)
    })


# ── INSIGHTS ──────────────────────────────────────────────────
@app.route("/api/insights", methods=["GET"])
def pattern_insights():
    needs = get_all_needs()
    assignments = get_all_assignments()

    completed = [n for n in needs if n.get("status") == "completed"]
    pending = [n for n in needs if n.get("status") == "pending"]
    total_people = sum(int(n.get("people_affected", 0)) for n in needs)

    # Category breakdown from real data
    category_counts = {}
    for n in needs:
        cat = n.get("category", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1
    top_cat = max(category_counts, key=category_counts.get) if category_counts else "N/A"

    # Avg resolution time from real assignment data
    resolution_times = []
    for a in assignments:
        if a.get("assigned_at") and a.get("completed_at"):
            try:
                start = datetime.fromisoformat(a["assigned_at"])
                end = datetime.fromisoformat(a["completed_at"])
                hours = (end - start).total_seconds() / 3600
                resolution_times.append(hours)
            except Exception:
                pass
    avg_hours = round(sum(resolution_times) / len(resolution_times), 1) if resolution_times else None

    insights = [
        {
            "icon": "📊",
            "title": "Most Common Need",
            "value": top_cat.replace("_", " ").title(),
            "detail": f"{category_counts.get(top_cat, 0)} of {len(needs)} total submissions"
        },
        {
            "icon": "⏱️",
            "title": "Avg Resolution Time",
            "value": f"{avg_hours} hrs" if avg_hours else "Not enough data yet",
            "detail": "Calculated from completed assignments"
        },
        {
            "icon": "👥",
            "title": "Total People Reached",
            "value": f"{total_people:,}",
            "detail": f"Across {len(needs)} needs in the system"
        },
        {
            "icon": "✅",
            "title": "Needs Resolved",
            "value": str(len(completed)),
            "detail": f"{len(pending)} still pending action"
        },
        {
            "icon": "📋",
            "title": "Total Assignments",
            "value": str(len(assignments)),
            "detail": f"{len(completed)} completed · {len(pending)} active"
        },
        {
            "icon": "🗂️",
            "title": "Category Breakdown",
            "value": " · ".join([f"{k}: {v}" for k, v in list(category_counts.items())[:3]]) or "No data",
            "detail": "Distribution of need types submitted"
        }
    ]

    return jsonify({
        "insights": insights,
        "data_points": len(needs),
        "note": "Computed from live Google Sheets data"
    })



# ── COMPLETE A TASK ───────────────────────────────────────────
@app.route("/api/needs/<need_id>/complete", methods=["POST"])
def complete_need(need_id):
    """
    Volunteer completed the task.
    1. Mark need as completed
    2. Log outcome to Assignments sheet
    3. Decrement volunteer assigned_count (frees them up)
    4. Find next best need for that volunteer (reallocation)
    """
    body = request.get_json() or {}
    outcome = body.get("outcome", "successful")
    feedback = body.get("feedback", "")

    # Step 1: Get the need to find assigned volunteer
    needs = get_all_needs()
    need = next((n for n in needs if str(n.get("id")) == str(need_id)), None)
    if not need:
        return jsonify({"error": "Need not found"}), 404

    assigned_vol_id = str(need.get("assigned_volunteer", ""))

    # Step 2: Mark need completed
    update_need(need_id, {"status": "completed"})

    # Step 3: Log to Assignments sheet
    complete_assignment(need_id, outcome, feedback)

    # Step 4: Free up volunteer
    reallocation_suggestion = None
    if assigned_vol_id:
        volunteers = get_all_volunteers()
        vol = next((v for v in volunteers if str(v.get("id")) == assigned_vol_id), None)
        if vol:
            new_count = max(0, int(vol.get("assigned_count", 1)) - 1)
            update_volunteer(assigned_vol_id, {
                "assigned_count": new_count,
                "availability": "available"
            })

            # Step 5: Smart reallocation — find next best need for freed volunteer
            remaining_needs = get_all_needs()
            pending = [n for n in remaining_needs if n.get("status") == "pending"]
            scored = score_all_needs(pending)

            if scored:
                # Update volunteer count in memory for matching
                vol_updated = dict(vol)
                vol_updated["assigned_count"] = new_count
                vol_updated["availability"] = "available"

                # Find best match for this volunteer across all pending needs
                best_need = None
                best_score = 0
                for pending_need in scored[:5]:  # Check top 5 priority needs
                    matches = find_top_matches(
                        pending_need, [vol_updated],
                        top_n=1, use_gemini=False
                    )
                    if matches and matches[0]["match_score"] > best_score:
                        best_score = matches[0]["match_score"]
                        best_need = pending_need

                if best_need:
                    reallocation_suggestion = {
                        "volunteer_name": vol.get("name"),
                        "suggested_need_id": best_need.get("id"),
                        "suggested_need_desc": best_need.get("description", "")[:100],
                        "suggested_need_urgency": best_need.get("urgency"),
                        "match_score": round(best_score, 1),
                        "message": f"{vol.get('name')} is now free. Best next match: {best_need.get('category')} need in {best_need.get('location')} (score: {round(best_score,1)})"
                    }

    return jsonify({
        "success": True,
        "need_id": need_id,
        "outcome": outcome,
        "reallocation": reallocation_suggestion
    })


# ── RESOURCE GAP ANALYSIS ─────────────────────────────────────
@app.route("/api/resource-gap", methods=["GET"])
def resource_gap():
    """
    Compares what skills are NEEDED vs what volunteers HAVE.
    Shows where the system is under-resourced.
    This is the core of 'intelligent allocation' — 
    not just matching, but identifying systemic gaps.
    """
    needs = get_all_needs()
    volunteers = get_all_volunteers()

    # Count needed skills from active needs
    needed = {}
    for n in needs:
        if n.get("status") != "completed":
            cat = n.get("category", "other")
            people = int(n.get("people_affected", 0))
            needed[cat] = needed.get(cat, 0) + 1

    # Count available volunteer skills
    available = {}
    skill_map = {
        "medical": ["medical", "first aid", "nurse", "paramedic", "health", "doctor"],
        "food": ["food", "nutrition", "meal", "ration", "distribution"],
        "logistics": ["logistics", "transport", "supply", "driving", "delivery"],
        "education": ["teaching", "education", "tutor", "school"],
        "mental_health": ["mental health", "counseling", "psycho", "trauma"],
        "shelter": ["shelter", "construction", "camp", "housing"]
    }

    for vol in volunteers:
        if str(vol.get("availability", "")).lower() == "available":
            skills_text = str(vol.get("skills", "")).lower()
            matched = False
            for category, keywords in skill_map.items():
                if any(kw in skills_text for kw in keywords):
                    available[category] = available.get(category, 0) + 1
                    matched = True
            if not matched:
                available["other"] = available.get("other", 0) + 1

    # Compute gap for each category
    all_categories = set(list(needed.keys()) + list(available.keys()))
    gaps = []
    for cat in all_categories:
        need_count = needed.get(cat, 0)
        avail_count = available.get(cat, 0)
        gap = need_count - avail_count
        gaps.append({
            "category": cat,
            "needs_count": need_count,
            "volunteers_available": avail_count,
            "gap": gap,
            "status": "critical_shortage" if gap >= 2
                      else "shortage" if gap == 1
                      else "balanced" if gap == 0
                      else "surplus"
        })

    gaps.sort(key=lambda x: x["gap"], reverse=True)

    return jsonify({
        "gaps": gaps,
        "total_active_needs": sum(needed.values()),
        "total_available_volunteers": len([v for v in volunteers
                                          if str(v.get("availability","")).lower() == "available"])
    })


# ── ENHANCED HEATMAP (needs + volunteer overlay) ──────────────
@app.route("/api/heatmap", methods=["GET"])
def heatmap_data():
    """
    Returns both need locations AND volunteer locations.
    Coordinators can see: where needs are vs where help is.
    This is the 'need vs availability' heatmap.
    """
    needs = get_all_needs()
    volunteers = get_all_volunteers()
    scored = score_all_needs(needs)

    need_points = []
    for n in scored:
        try:
            lat = float(n.get("lat") or 0)
            lng = float(n.get("lng") or 0)
            if lat == 0 and lng == 0:
                continue
            need_points.append({
                "type": "need",
                "lat": lat,
                "lng": lng,
                "priority_score": float(n.get("priority_score", 0)),
                "urgency": n.get("urgency", "low"),
                "category": n.get("category", "other"),
                "description": (n.get("description", ""))[:80],
                "people_affected": n.get("people_affected", 0),
                "status": n.get("status", "pending"),
                "id": n.get("id", ""),
                "ngo_name": n.get("ngo_name", "")
            })
        except Exception:
            continue

    vol_points = []
    for v in volunteers:
        try:
            lat = float(v.get("lat") or 0)
            lng = float(v.get("lng") or 0)
            if lat == 0 and lng == 0:
                continue
            vol_points.append({
                "type": "volunteer",
                "lat": lat,
                "lng": lng,
                "name": v.get("name", ""),
                "skills": v.get("skills", ""),
                "availability": v.get("availability", ""),
                "assigned_count": v.get("assigned_count", 0),
                "id": v.get("id", "")
            })
        except Exception:
            continue

    return jsonify(sanitize({
        "need_points": need_points,
        "volunteer_points": vol_points,
        "need_count": len(need_points),
        "volunteer_count": len(vol_points)
    }))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)