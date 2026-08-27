"""
Seeds the two fixture organizations required by the evaluation brief:
ABC Construction and XYZ Builders, each with an owner and a member user.

Run with:  python -m scripts.seed

Prints the generated API keys - these are LOCAL DEV FIXTURES ONLY, not
real secrets, and are safe to commit as example values (they only work
against a local/dev database you control).
"""
import secrets
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import Base, engine, SessionLocal
from app import models
from app.auth import hash_api_key


def gen_key(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(models.Organization).filter(
            models.Organization.name.in_(["ABC Construction", "XYZ Builders"])
        ).all()
        if existing:
            print("Fixture organizations already exist. Skipping seed.")
            print("(API keys are hashed at rest and cannot be re-printed - re-run against")
            print(" a fresh database if you need new fixture keys.)")
            return

        fixtures = [
            {
                "org_name": "ABC Construction",
                "users": [
                    {"email": "owner@abc-construction.example", "role": models.UserRole.owner, "department": "operations"},
                    {"email": "member@abc-construction.example", "role": models.UserRole.member, "department": "operations"},
                ],
            },
            {
                "org_name": "XYZ Builders",
                "users": [
                    {"email": "owner@xyz-builders.example", "role": models.UserRole.owner, "department": "operations"},
                    {"email": "member@xyz-builders.example", "role": models.UserRole.member, "department": "operations"},
                ],
            },
        ]

        print("Seeded fixture credentials (dev/local only):\n")
        for fx in fixtures:
            org = models.Organization(name=fx["org_name"])
            db.add(org)
            db.flush()
            for u in fx["users"]:
                key = gen_key("dev")
                user = models.User(
                    organization_id=org.id,
                    email=u["email"],
                    api_key_hash=hash_api_key(key),
                    role=u["role"],
                    department=u["department"],
                )
                db.add(user)
                print(f"  {fx['org_name']:20s} {u['role'].value:8s} {u['email']:30s} api_key={key}")
        db.commit()
        print("\nUse these values with the X-API-Key header when calling the API.")
        print("These raw keys are shown ONCE - only the hash is stored. Save them now.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
