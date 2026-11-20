#!/usr/bin/env python3
"""
scripts/seed_db.py
Seeds the database with default dev accounts, villages, and road network data.
Usage: python scripts/seed_db.py
"""
import os
import sys

# Add repo root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.app import create_app, db
from backend.models.user import User, UserRole
from backend.models.village import Village
from backend.models.road_segment import RoadSegment

app = create_app(os.environ.get("FLASK_ENV", "development"))

def seed():
    with app.app_context():
        # 1. Users
        users_data = [
            ("coord@georesq.com", "Admin123!", "Admin Coordinator", UserRole.coordinator),
            ("coordinator@georesq.dev", "Password1!", "Priya Coordinator", UserRole.coordinator),
            ("citizen1@georesq.dev", "Password1!", "Ravi Citizen", UserRole.citizen),
            ("citizen2@georesq.dev", "Password1!", "Meena Citizen", UserRole.citizen),
        ]
        for email, password, name, role in users_data:
            existing = db.session.query(User).filter_by(email=email).first()
            if not existing:
                user = User(email=email, full_name=name, role=role, is_active=True)
                user.set_password(password)
                db.session.add(user)
                print(f"Created user: {email} ({role.value})")

        # 2. Villages
        villages_data = [
            (1001, 'Shimoga', 14.0027, 75.5681, 274000, True),
            (1002, 'Chikmagalur', 13.3153, 75.7754, 60000, True),
            (1003, 'Sringeri', 13.4178, 75.2543, 8000, True),
            (1004, 'Kalasa', 13.3419, 75.3611, 3500, False),
            (1005, 'Hornadu', 13.3876, 75.1951, 1200, False),
            (1006, 'Balehonnur', 13.1753, 75.5081, 2200, False),
            (1007, 'Mudigere', 13.1308, 75.6494, 4000, False),
            (1008, 'Kottigehara', 13.2528, 75.4658, 800, False),
        ]
        for osm_id, name, lat, lng, pop, is_town in villages_data:
            existing = db.session.query(Village).filter_by(osm_node_id=osm_id).first()
            if not existing:
                v = Village(osm_node_id=osm_id, name=name, lat=lat, lng=lng, population=pop, is_town=is_town)
                db.session.add(v)
                print(f"Added village: {name}")

        # 3. Road segments
        roads_data = [
            (2001, 'NH-173 (Shimoga–Chikmagalur)', 'primary', 1001, 1002, 14.0027, 75.5681, 13.3153, 75.7754, 90000.0, False),
            (2002, 'SH-57 (Chikmagalur–Sringeri)', 'secondary', 1002, 1003, 13.3153, 75.7754, 13.4178, 75.2543, 55000.0, False),
            (2003, 'MDR (Sringeri–Kalasa)', 'tertiary', 1003, 1004, 13.4178, 75.2543, 13.3419, 75.3611, 15000.0, False),
            (2004, 'MDR (Kalasa–Hornadu)', 'tertiary', 1004, 1005, 13.3419, 75.3611, 13.3876, 75.1951, 22000.0, False),
            (2005, 'MDR (Sringeri–Balehonnur)', 'tertiary', 1003, 1006, 13.4178, 75.2543, 13.1753, 75.5081, 32000.0, False),
            (2006, 'SH (Balehonnur–Mudigere)', 'secondary', 1006, 1007, 13.1753, 75.5081, 13.1308, 75.6494, 18000.0, False),
            (2007, 'MDR (Kalasa–Kottigehara)', 'tertiary', 1004, 1008, 13.3419, 75.3611, 13.2528, 75.4658, 20000.0, False),
        ]
        for osm_id, name, hw_type, s_id, e_id, s_lat, s_lng, e_lat, e_lng, length, blocked in roads_data:
            existing = db.session.query(RoadSegment).filter_by(osm_way_id=osm_id).first()
            if not existing:
                r = RoadSegment(
                    osm_way_id=osm_id,
                    name=name,
                    highway_type=hw_type,
                    start_node_id=s_id,
                    end_node_id=e_id,
                    start_lat=s_lat,
                    start_lng=s_lng,
                    end_lat=e_lat,
                    end_lng=e_lng,
                    length_m=length,
                    blocked=blocked
                )
                db.session.add(r)
                print(f"Added road segment: {name}")

        db.session.commit()
        print("✅ Database seeded successfully.")

if __name__ == "__main__":
    seed()
