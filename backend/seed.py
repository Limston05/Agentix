import os
import random
import time
import json
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import json_util
from faker import Faker

def load_env(env_path=".env"):
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                os.environ[key] = val

def save_mock_db(collections):
    mock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_db")
    os.makedirs(mock_dir, exist_ok=True)
    for col_name, data in collections.items():
        filepath = os.path.join(mock_dir, f"{col_name}.json")
        print(f"Saving mock collection '{col_name}' to {filepath}...")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(json_util.dumps(data, indent=2))
    print("Mock database files written successfully.")

def seed_database():
    print("Starting database seeding process...")
    start_time = time.time()
    
    # Load env vars
    load_env()
    mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    
    # Check if MongoDB is running
    use_mock = False
    try:
        print(f"Connecting to MongoDB at {mongodb_uri}...")
        client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        db = client["D2C_Operations"]
        print("Connected successfully to MongoDB server. Will seed to MongoDB database.")
    except Exception as e:
        print(f"Could not connect to MongoDB server: {e}")
        print("Switching to mock database mode (JSON file fallback).")
        use_mock = True
    
    if not use_mock:
        # Drop existing collections if they exist to ensure clean state
        print("Dropping existing collections...")
        db["Inventory"].drop()
        db["Customers"].drop()
        db["Orders"].drop()
        db["PurchaseOrders"].drop()
    
    fake = Faker()
    
    # 1. Seed Inventory (50 items)
    print("Generating Inventory...")
    categories = ["Electronics", "Apparel", "Home & Kitchen", "Fitness", "Office Supply", "Footwear", "Accessories"]
    adjectives = ["Premium", "Ergonomic", "Wireless", "Smart", "Eco-friendly", "Portable", "Heavy-Duty", "Compact", "Luxury"]
    nouns = ["Headphones", "Water Bottle", "Desk Lamp", "Backpack", "Yoga Mat", "Coffee Mug", "Smartwatch", "Keyboard", "Mouse Pad", "Wallet"]
    
    inventory_docs = []
    skus = []
    for i in range(1, 51):
        sku = f"SKU-{i:03d}"
        skus.append(sku)
        product_name = f"{random.choice(adjectives)} {random.choice(nouns)} {i}"
        stock_quantity = random.randint(10, 1000)
        warehouse_location = f"WH-{random.choice(['A', 'B', 'C'])}-Row{random.randint(1, 15)}-Shelf{random.choice(['A', 'B', 'C', 'D'])}"
        
        inventory_docs.append({
            "product_name": product_name,
            "sku": sku,
            "stock_quantity": stock_quantity,
            "warehouse_location": warehouse_location,
            "category": random.choice(categories),
            "unit_price": round(random.uniform(9.99, 299.99), 2)
        })
    
    if not use_mock:
        db["Inventory"].insert_many(inventory_docs)
    print(f"Generated {len(inventory_docs)} Inventory items.")
    
    # 2. Seed Customers (1,000 customers)
    print("Generating Customers...")
    customer_docs = []
    customer_ids = []
    for i in range(1, 1001):
        cust_id = f"CUST-{i:04d}"
        customer_ids.append(cust_id)
        customer_docs.append({
            "customer_id": cust_id,
            "name": fake.name(),
            "location": {
                "city": fake.city()
            },
            "email": fake.email(),
            "created_at": fake.date_time_between(start_date="-2y", end_date="-1y")
        })
        
    if not use_mock:
        db["Customers"].insert_many(customer_docs)
    print(f"Generated {len(customer_docs)} Customers.")
    
    # 3. Seed Orders (50,000 orders)
    print("Generating 50,000 Orders...")
    order_docs = []
    
    # Pre-generate dates to make it faster
    base_date = datetime.now()
    
    # Insert in chunks of 5000 for efficiency
    chunk_size = 5000
    total_orders = 50000
    
    for i in range(1, total_orders + 1):
        order_id = f"ORD-{i:06d}"
        cust_id = random.choice(customer_ids)
        total_amount = round(random.uniform(15.00, 1500.00), 2)
        
        # Distribute dates realistically over the last 365 days
        random_days = random.randint(0, 365)
        random_seconds = random.randint(0, 86400)
        order_date = base_date - timedelta(days=random_days, seconds=random_seconds)
        
        num_items = random.randint(1, 4)
        items = []
        for _ in range(num_items):
            item_sku = random.choice(skus)
            qty = random.randint(1, 5)
            items.append({
                "sku": item_sku,
                "quantity": qty
            })
            
        order_docs.append({
            "order_id": order_id,
            "customer_id": cust_id,
            "total_amount": total_amount,
            "date": order_date,
            "items": items
        })
        
        if not use_mock and len(order_docs) >= chunk_size:
            db["Orders"].insert_many(order_docs)
            print(f"Inserted {i} / {total_orders} orders to MongoDB...")
            order_docs = []
            
    if not use_mock and order_docs:
        db["Orders"].insert_many(order_docs)
        
    print(f"Generated {total_orders} Orders.")
    
    # Always write mock database files to disk as a fallback/reference
    print("Saving database snapshot to JSON files...")
    all_orders = order_docs if use_mock else list(db["Orders"].find())
    save_mock_db({
        "Inventory": inventory_docs,
        "Customers": customer_docs,
        "Orders": all_orders,
        "PurchaseOrders": []
    })
    
    if not use_mock:
        # Create indexes
        print("Creating indexes on MongoDB collections...")
        db["Inventory"].create_index("sku", unique=True)
        db["Customers"].create_index("customer_id", unique=True)
        db["Orders"].create_index("order_id", unique=True)
        db["Orders"].create_index("customer_id")
        db["Orders"].create_index("date")
    
    elapsed_time = time.time() - start_time
    print(f"Seeding completed in {elapsed_time:.2f} seconds!")

if __name__ == "__main__":
    seed_database()
