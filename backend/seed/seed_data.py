"""Seed KisanBaazar with realistic demo products and a demo farmer."""
import asyncio
import os
import uuid
import bcrypt
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv(Path(__file__).parent.parent / ".env")
client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]


def now():
    return datetime.now(timezone.utc).isoformat()


DEMO_FARMER = {
    "user_id": "user_demofarmer01",
    "email": "farmer@kisanbaazar.in",
    "password": bcrypt.hashpw(b"farmer123", bcrypt.gensalt()).decode(),
    "name": "Ramesh Patil",
    "role": "farmer",
    "phone": "+919876543210",
    "location": "Nashik, Maharashtra",
    "picture": None,
    "verified": True,
    "created_at": now(),
}

DEMO_BUYER = {
    "user_id": "user_demobuyer01",
    "email": "buyer@kisanbaazar.in",
    "password": bcrypt.hashpw(b"buyer123", bcrypt.gensalt()).decode(),
    "name": "Anita Sharma",
    "role": "buyer",
    "phone": "+919812345678",
    "location": "Mumbai, Maharashtra",
    "picture": None,
    "verified": True,
    "created_at": now(),
}

DEMO_ADMIN = {
    "user_id": "user_demoadmin01",
    "email": "admin@kisanbaazar.in",
    "password": bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode(),
    "name": "KisanBaazar Admin",
    "role": "admin",
    "verified": True,
    "created_at": now(),
}

PRODUCTS = [
    {"title": "Premium Alphonso Mangoes", "description": "GI-tagged Ratnagiri Alphonso, hand-picked at peak ripeness. Naturally ripened, no carbide.",
     "category": "fruits", "price": 850, "unit": "dozen", "moq": 2, "available_qty": 500,
     "quality_grade": "Export", "organic": True, "export_ready": True,
     "images": ["https://images.unsplash.com/photo-1553279768-865429fa0078?w=800"],
     "location": "Ratnagiri", "state": "Maharashtra", "harvest_date": "2026-02-10"},
    {"title": "Basmati Rice 1121", "description": "Aged 18 months. Long grain, aromatic. Suitable for export markets - Middle East, EU.",
     "category": "rice", "price": 95, "unit": "kg", "moq": 100, "available_qty": 5000,
     "quality_grade": "Export", "organic": False, "export_ready": True,
     "images": ["https://images.unsplash.com/photo-1586201375761-83865001e31c?w=800"],
     "location": "Karnal", "state": "Haryana", "harvest_date": "2025-11-20"},
    {"title": "Organic Turmeric Powder", "description": "Lakadong variety, 5%+ curcumin content. NPOP & USDA certified organic.",
     "category": "spices", "price": 320, "unit": "kg", "moq": 10, "available_qty": 800,
     "quality_grade": "Export", "organic": True, "export_ready": True,
     "images": ["https://images.unsplash.com/photo-1615485500704-8e990f9900f7?w=800"],
     "location": "Erode", "state": "Tamil Nadu", "harvest_date": "2026-01-15"},
    {"title": "Fresh Pomegranate (Bhagwa)", "description": "Deep red, sweet, large size. Direct from Solapur farms.",
     "category": "fruits", "price": 120, "unit": "kg", "moq": 50, "available_qty": 1200,
     "quality_grade": "A", "organic": False, "export_ready": True,
     "images": ["https://images.unsplash.com/photo-1541344999736-83eca272f6fc?w=800"],
     "location": "Solapur", "state": "Maharashtra", "harvest_date": "2026-02-05"},
    {"title": "Organic Tomatoes", "description": "Pesticide-free, vine-ripened. Perfect for restaurants and home cooks.",
     "category": "vegetables", "price": 45, "unit": "kg", "moq": 20, "available_qty": 600,
     "quality_grade": "A", "organic": True, "export_ready": False,
     "images": ["https://images.unsplash.com/photo-1592924357228-91a4daadcfea?w=800"],
     "location": "Pune", "state": "Maharashtra", "harvest_date": "2026-02-18"},
    {"title": "Wheat (Sharbati)", "description": "MP Sharbati premium wheat - high protein, golden grain. Mill-ready.",
     "category": "grains", "price": 38, "unit": "kg", "moq": 500, "available_qty": 20000,
     "quality_grade": "A", "organic": False, "export_ready": False,
     "images": ["https://images.unsplash.com/photo-1574323347407-f5e1ad6d020b?w=800"],
     "location": "Sehore", "state": "Madhya Pradesh", "harvest_date": "2025-04-15"},
    {"title": "Wild Forest Honey", "description": "Raw, unprocessed, sourced from Sundarbans. Cold-extracted, glass-bottled.",
     "category": "honey", "price": 650, "unit": "kg", "moq": 5, "available_qty": 200,
     "quality_grade": "Export", "organic": True, "export_ready": True,
     "images": ["https://images.unsplash.com/photo-1587049352846-4a222e784d38?w=800"],
     "location": "Sundarbans", "state": "West Bengal", "harvest_date": "2026-01-08"},
    {"title": "Toor Dal (Arhar)", "description": "Unpolished, freshly milled. From Gulbarga - the toor capital.",
     "category": "pulses", "price": 110, "unit": "kg", "moq": 50, "available_qty": 3000,
     "quality_grade": "A", "organic": False, "export_ready": False,
     "images": ["https://images.unsplash.com/photo-1604908554049-0bca5dfb1f8e?w=800"],
     "location": "Gulbarga", "state": "Karnataka", "harvest_date": "2025-12-12"},
    {"title": "Marigold Flowers (Bulk)", "description": "Fresh garlands & loose flowers. Daily harvest. Wedding & temple bulk supply.",
     "category": "flowers", "price": 80, "unit": "kg", "moq": 25, "available_qty": 400,
     "quality_grade": "A", "organic": False, "export_ready": False,
     "images": ["https://images.unsplash.com/photo-1597481499666-9bd71d4dc6db?w=800"],
     "location": "Bengaluru Rural", "state": "Karnataka", "harvest_date": "2026-02-19"},
    {"title": "A2 Gir Cow Ghee", "description": "Bilona method, 25L milk = 1L ghee. From desi Gir cows. Lab tested.",
     "category": "dairy", "price": 2400, "unit": "kg", "moq": 1, "available_qty": 150,
     "quality_grade": "Export", "organic": True, "export_ready": True,
     "images": ["https://images.unsplash.com/photo-1628088062854-d1870b4553da?w=800"],
     "location": "Anand", "state": "Gujarat", "harvest_date": "2026-02-12"},
    {"title": "Cardamom (Elaichi) - Auction", "description": "Premium 8mm bold green cardamom. Live auction - 7 days. Idukki estate.",
     "category": "spices", "price": 2800, "unit": "kg", "moq": 5, "available_qty": 100,
     "quality_grade": "Export", "organic": False, "export_ready": True,
     "images": ["https://images.unsplash.com/photo-1599909533730-ce6b3ff8b6a3?w=800"],
     "location": "Idukki", "state": "Kerala", "harvest_date": "2026-01-25",
     "auction": True, "auction_end": "2026-02-28T18:00:00Z"},
    {"title": "Organic Quinoa Seeds", "description": "Andean variety, high altitude grown in Himachal. Lab certified.",
     "category": "seeds", "price": 480, "unit": "kg", "moq": 10, "available_qty": 250,
     "quality_grade": "Export", "organic": True, "export_ready": True,
     "images": ["https://images.unsplash.com/photo-1586201375761-83865001e31c?w=800"],
     "location": "Lahaul-Spiti", "state": "Himachal Pradesh", "harvest_date": "2025-10-22"},
]


async def main():
    await db.users.delete_many({"email": {"$in": [DEMO_FARMER["email"], DEMO_BUYER["email"], DEMO_ADMIN["email"]]}})
    await db.users.insert_many([DEMO_FARMER, DEMO_BUYER, DEMO_ADMIN])

    await db.products.delete_many({"farmer_id": DEMO_FARMER["user_id"]})
    docs = []
    for p in PRODUCTS:
        doc = {
            "product_id": f"prod_{uuid.uuid4().hex[:10]}",
            "farmer_id": DEMO_FARMER["user_id"],
            "farmer_name": DEMO_FARMER["name"],
            "country": "India",
            "auction": False,
            "auction_end": None,
            **p,
            "created_at": now(),
        }
        doc["current_bid"] = p["price"] if doc.get("auction") else None
        docs.append(doc)
    await db.products.insert_many(docs)
    print(f"Seeded {len(docs)} products and 3 users.")


if __name__ == "__main__":
    asyncio.run(main())
