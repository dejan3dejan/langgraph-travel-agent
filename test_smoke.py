"""Smoke tests — validates imports, schemas, LLM config, and graph compilation (no DB/API needed)."""

import sys


def main():
    errors = []

    # 1. Core imports
    try:
        from core.geo import group_places_by_zone, optimize_day_route
        from core.llm import get_llm_for_role
        from core.logistics import haversine_distance
        from core.schemas import ItineraryCritique, Restaurant, UserPreferences

        print("[OK] All core imports")
    except Exception as e:
        errors.append(f"Core imports: {e}")
        print(f"[FAIL] Core imports: {e}")

    # 2. Haversine distance
    try:
        d = haversine_distance(48.8566, 2.3522, 48.8606, 2.3376)
        assert 0.5 < d < 2.0, f"Unexpected distance: {d}"
        print(f"[OK] Haversine: {d:.2f} km")
    except Exception as e:
        errors.append(f"Haversine: {e}")
        print(f"[FAIL] Haversine: {e}")

    # 3. Zone grouping
    try:
        places = [
            {"name": "Near", "lat": 48.857, "lon": 2.352},
            {"name": "Medium", "lat": 48.870, "lon": 2.332},
            {"name": "Remote", "lat": 49.000, "lon": 2.500},
        ]
        zones = group_places_by_zone(places, 48.856, 2.352)
        assert len(zones["near"]) >= 1
        assert len(zones["remote"]) >= 1
        print(
            f"[OK] Zone grouping: near={len(zones['near'])}, medium={len(zones['medium'])}, far={len(zones['far'])}, remote={len(zones['remote'])}"
        )
    except Exception as e:
        errors.append(f"Zone grouping: {e}")
        print(f"[FAIL] Zone grouping: {e}")

    # 4. Pydantic schemas
    try:
        r = Restaurant(name="Test", address="123 St", cuisine="Italian", price_level="$$", rating=4.5, reason="good")
        d = r.model_dump()
        assert d["name"] == "Test"

        prefs = UserPreferences(
            destination="Paris", start_location="NYC", duration="3 days", budget="Medium", interests="art"
        )
        assert prefs.destination == "Paris"
        assert prefs.needs_accommodation is None  # unknown until stated/inferred

        critique = ItineraryCritique(approved=True, feedback="Good", score=9, missing_data=[])
        assert critique.approved is True
        print("[OK] Pydantic schemas (Restaurant, UserPreferences, ItineraryCritique)")
    except Exception as e:
        errors.append(f"Schemas: {e}")
        print(f"[FAIL] Schemas: {e}")

    # 5. LLM role config (no API calls)
    try:
        models = {}
        for role in ["interviewer", "compiler", "critic", "extraction", "research"]:
            llm = get_llm_for_role(role)
            models[role] = llm.model
        print(f"[OK] LLM roles: {models}")
    except Exception as e:
        errors.append(f"LLM config: {e}")
        print(f"[FAIL] LLM config: {e}")

    # 6. Graph compilation
    try:
        from core.graph import app

        nodes = list(app.get_graph().nodes.keys())
        assert "interviewer" in nodes
        assert "compiler" in nodes
        assert "critic" in nodes
        assert "logistics" in nodes
        print(f"[OK] Graph compiled, nodes: {nodes}")
    except Exception as e:
        errors.append(f"Graph compilation: {e}")
        print(f"[FAIL] Graph compilation: {e}")

    # 7. FastAPI app import
    try:
        from api.main import app as fastapi_app

        routes = [r.path for r in fastapi_app.routes]
        assert "/health" in routes
        assert "/api/chat" in routes
        print("[OK] FastAPI app, routes include /health and /api/chat")
    except Exception as e:
        errors.append(f"FastAPI import: {e}")
        print(f"[FAIL] FastAPI import: {e}")

    # 8. Route optimization
    try:
        route = optimize_day_route(
            [{"name": "A", "lat": 48.857, "lon": 2.352}, {"name": "B", "lat": 48.860, "lon": 2.349}],
            48.856,
            2.352,
        )
        assert "optimized_order" in route
        assert len(route["optimized_order"]) == 2
        print(f"[OK] Route optimization: {route['total_distance_km']} km")
    except Exception as e:
        errors.append(f"Route optimization: {e}")
        print(f"[FAIL] Route optimization: {e}")

    # Summary
    print()
    if errors:
        print(f"FAILED: {len(errors)} test(s)")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("=== ALL 8 SMOKE TESTS PASSED ===")
        sys.exit(0)


if __name__ == "__main__":
    main()
