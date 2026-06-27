import os
import json
import datetime
import random
import time
from datetime import timedelta
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import mongomock
from google import genai
from google.genai import types
from bson import json_util

# Load env variables
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

load_env()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Initialize MongoDB client or fallback to mongomock
db = None
use_mock_db = False

try:
    print(f"Connecting to MongoDB at {MONGODB_URI}...")
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=2000)
    mongo_client.admin.command('ping')
    db = mongo_client["D2C_Operations"]
    print("Successfully connected to live MongoDB server.")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    print("Switching to in-memory mongomock database...")
    use_mock_db = True

if use_mock_db:
    mock_client = mongomock.MongoClient()
    db = mock_client["D2C_Operations"]
    
    # Load snapshot from local JSON files
    mock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_db")
    for col_name in ["Inventory", "Customers", "Orders", "PurchaseOrders"]:
        filepath = os.path.join(mock_dir, f"{col_name}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    docs = json_util.loads(f.read())
                    if docs:
                        db[col_name].insert_many(docs)
                print(f"Loaded {db[col_name].count_documents({})} documents into mock '{col_name}' collection.")
            except Exception as load_err:
                print(f"Failed to load mock data for '{col_name}': {load_err}")

# Initialize FastAPI
app = FastAPI(title="D2C Operations Executive API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Rate Limiting -----------------
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 15     # max requests per window
ip_request_timestamps = {}

def check_rate_limit(ip: str):
    current_time = time.time()
    if ip not in ip_request_timestamps:
        ip_request_timestamps[ip] = []
    
    # Clean up timestamps older than 1 minute
    ip_request_timestamps[ip] = [t for t in ip_request_timestamps[ip] if current_time - t < RATE_LIMIT_WINDOW]
    
    if len(ip_request_timestamps[ip]) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Maximum 15 requests per minute. Please try again shortly."
        )
    
    ip_request_timestamps[ip].append(current_time)

# ----------------- Request / Response Models -----------------
class MessageModel(BaseModel):
    role: str # 'user' or 'model'
    content: str
    route: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    history: List[MessageModel]
    user_id: Optional[str] = None

class ChatResponse(BaseModel):
    agent_reply: str
    route: str

class LoginRequest(BaseModel):
    email: str
    name: str
    provider: str

class ConversationModel(BaseModel):
    conversation_id: str
    user_id: str
    title: str
    messages: List[MessageModel]

class RenameRequest(BaseModel):
    title: str

# Retrieve GenAI client with secure proxy key or header key
def get_gemini_client(provider_key: Optional[str] = None):
    print("====== API KEY DEBUG ======")
    print(f"1. Key sent from frontend: {provider_key}")
    print(f"2. Key loaded from .env:   {os.environ.get('GEMINI_API_KEY')}")
    print("===========================")
    
    # Check if a custom key was passed in request headers
    api_key = provider_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="Google GenAI API key is missing. Please add the API key in settings or configure server environment."
        )
    try:
        return genai.Client(api_key=api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Google API Key configuration: {e}")

# ----------------- Tools -----------------

def execute_dynamic_query(collection_name: str, json_query: str) -> str:
    """
    Executes a dynamic MongoDB query (find filter or aggregation pipeline) on a specified collection.
    
    Args:
        collection_name: The target collection. Must be one of 'Inventory', 'Customers', 'Orders', or 'PurchaseOrders'.
        json_query: A valid JSON string containing either a find filter (e.g. '{"sku": "SKU-001"}') or an aggregation pipeline array (e.g. '[{"$match": ...}, {"$group": ...}]').
    """
    if db is None:
        return "Error: Database connection is offline."
        
    if collection_name not in ["Inventory", "Customers", "Orders", "PurchaseOrders"]:
        return f"Error: Invalid collection '{collection_name}'. Allowed: Inventory, Customers, Orders, PurchaseOrders."
        
    try:
        query_data = json_util.loads(json_query)
    except Exception as e:
        return f"Error: Failed to parse query as JSON. Ensure you use standard quotes. Details: {e}"

    try:
        coll = db[collection_name]
        if isinstance(query_data, list):
            # Aggregation pipeline
            has_limit = any("$limit" in stage for stage in query_data)
            if not has_limit:
                query_data.append({"$limit": 50})
            results = list(coll.aggregate(query_data))
        else:
            # Find filter
            results = list(coll.find(query_data).limit(50))
            
        return json_util.dumps(results, indent=2)
    except Exception as e:
        return f"Error executing MongoDB query: {e}"


def predict_seasonal_demand(sku: str) -> str:
    """
    Calculates a mathematical 6-month time-series demand forecast for a product SKU based on the current month.
    
    Args:
        sku: The product SKU (e.g., 'SKU-001').
    """
    digits = "".join([c for c in sku if c.isdigit()])
    seed_val = int(digits) if digits else 100
    
    old_state = random.getstate()
    random.seed(seed_val)
    
    current_date = datetime.datetime.now()
    base_demand = 100 + (seed_val % 400)
    is_summer_peak = (seed_val % 2 == 1)
    
    forecast_data = []
    for i in range(6):
        future_date = current_date + timedelta(days=30 * i)
        month_name = future_date.strftime("%B %Y")
        month_num = future_date.month
        
        if is_summer_peak:
            if month_num in [6, 7, 8]:
                multiplier = 1.5 + random.uniform(0.1, 0.4)
            elif month_num in [11, 12, 1]:
                multiplier = 0.5 + random.uniform(-0.1, 0.1)
            else:
                multiplier = 1.0 + random.uniform(-0.1, 0.1)
        else:
            if month_num in [11, 12, 1]:
                multiplier = 1.8 + random.uniform(0.1, 0.4)
            elif month_num in [6, 7, 8]:
                multiplier = 0.4 + random.uniform(-0.1, 0.1)
            else:
                multiplier = 1.0 + random.uniform(-0.1, 0.1)
                
        forecasted_units = int(base_demand * multiplier)
        forecast_data.append({
            "Month": month_name,
            "SKU": sku,
            "Forecasted Demand (Units)": forecasted_units,
            "Confidence Interval": f"{int(forecasted_units * 0.9)} - {int(forecasted_units * 1.1)}",
            "Growth Rate": f"{round((multiplier - 1.0) * 100, 1):+}%"
        })
        
    random.setstate(old_state)
    return json.dumps(forecast_data, indent=2)


def create_purchase_order(sku: str, quantity: int) -> str:
    """
    Creates a new Purchase Order in the 'PurchaseOrders' collection for restocking inventory.
    
    Args:
        sku: The SKU of the item to purchase (e.g., 'SKU-001').
        quantity: The quantity to order (must be positive).
    """
    if db is None:
        return "Error: Database connection is offline."
        
    if quantity <= 0:
        return "Error: Quantity must be a positive integer."
        
    try:
        item = db["Inventory"].find_one({"sku": sku})
        if not item:
            return f"Error: SKU '{sku}' does not exist in Inventory."
            
        last_po = db["PurchaseOrders"].find_one(sort=[("purchase_order_id", -1)])
        if last_po and last_po.get("purchase_order_id"):
            try:
                last_num = int(last_po["purchase_order_id"].split("-")[1])
                new_id = f"PO-{last_num + 1:05d}"
            except Exception:
                new_id = f"PO-{random.randint(10000, 99999)}"
        else:
            new_id = "PO-00001"
            
        unit_price = item.get("unit_price", 25.0)
        total_cost = round(quantity * unit_price, 2)
        
        po_doc = {
            "purchase_order_id": new_id,
            "sku": sku,
            "product_name": item["product_name"],
            "quantity": quantity,
            "unit_price": unit_price,
            "total_cost": total_cost,
            "status": "Pending",
            "date": datetime.datetime.now(),
            "warehouse_location": item.get("warehouse_location", "Main Warehouse")
        }
        
        db["PurchaseOrders"].insert_one(po_doc)
        
        # Save change back to JSON file if using mock db
        if use_mock_db:
            mock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_db")
            filepath = os.path.join(mock_dir, "PurchaseOrders.json")
            try:
                all_pos = list(db["PurchaseOrders"].find())
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(json_util.dumps(all_pos, indent=2))
            except Exception as write_err:
                print(f"Failed to write mock PurchaseOrders: {write_err}")
                
        return json.dumps({
            "status": "Success",
            "message": f"Successfully created Purchase Order {new_id}",
            "purchase_order_id": new_id,
            "sku": sku,
            "product_name": item["product_name"],
            "quantity": quantity,
            "total_cost": total_cost,
            "status": "Pending",
            "warehouse_location": item.get("warehouse_location", "Main Warehouse")
        }, default=str)
    except Exception as e:
        return f"Error creating purchase order: {e}"

# ----------------- Supervisor & Routing -----------------

def route_request(user_message: str, history: List[MessageModel], provider_key: Optional[str] = None) -> str:
    """
    Calls Gemini to classify the request into ANALYTICAL, OPERATIONAL, or GENERAL.
    """
    try:
        client = get_gemini_client(provider_key)
    except Exception as e:
        print(f"Error getting Gemini client: {e}")
        return "GENERAL"
        
    context = ""
    for msg in history[-4:]:
        context += f"{msg.role.upper()}: {msg.content}\n"
        
    prompt = f"""
    You are the Supervisor Agent for a D2C Operations web application.
    Your task is to classify the user's latest message into one of three categories:
    
    1. ANALYTICAL: The user wants to query data, check stock, list orders, analyze sales, find customer details, or run demand forecasts.
    2. OPERATIONAL: The user wants to make changes, restock inventory, or create purchase orders.
    3. GENERAL: The user is greeting you, saying goodbye, asking what you can do, or having a general conversation.
    
    Recent Chat Context:
    {context}
    
    User Message: "{user_message}"
    
    Respond with EXACTLY one word: "ANALYTICAL", "OPERATIONAL", or "GENERAL".
    Do not include any quotes, explanations, markdown, or other text.
    """
    
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        route = response.text.strip().upper()
        for word in ["ANALYTICAL", "OPERATIONAL", "GENERAL"]:
            if word in route:
                return word
        return "GENERAL"
    except Exception as e:
        print(f"Error in Supervisor Agent routing: {e}")
        return "GENERAL"

# ----------------- Sub-Agent Execution -----------------

def run_data_analyst(user_message: str, history: List[MessageModel], provider_key: Optional[str] = None) -> str:
    try:
        client = get_gemini_client(provider_key)
    except Exception as e:
        return f"Gemini client initialization failed: {e}"
        
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
    system_instruction = f"""
    You are the D2C Operations Data Analyst Agent.
    TODAY'S DATE IS: {current_date}. Use this date as your baseline for any time-based queries (e.g., "last year", "last 6 months").
    
    Your task is to help the user retrieve, search, aggregate, and analyze data from the D2C Operations database.
    You must use the provided tools to execute queries or forecasts.
    
    You have access to 4 MongoDB collections:
    1. Inventory (fields: product_name, sku, stock_quantity, warehouse_location, category, unit_price)
    2. Customers (fields: customer_id, name, location: {{ city }}, email, created_at)
    3. Orders (fields: order_id, customer_id, total_amount, date, items: [{{sku, quantity}}])
    4. PurchaseOrders (fields: purchase_order_id, sku, product_name, quantity, total_cost, status, date, warehouse_location)
    
    Important MongoDB query guidelines:
    - Dates in the Orders database are stored as Date objects. In standard MQL JSON, they are formatted as `{{"$date": "YYYY-MM-DDTHH:MM:SSZ"}}`.
      Example: `{{"date": {{"$gte": {{"$date": "2026-01-01T00:00:00Z"}}}}}}`.
    - If compiling an aggregation pipeline, write a valid JSON array of pipeline stages.
    - If compiling a find query, write a valid JSON dictionary.
    - Ensure your MongoDB JSON queries are syntactically valid and use double quotes.
    
    Your Available Tools:
    1. execute_dynamic_query(collection_name: str, json_query: str): Runs MQL find or aggregate queries and returns results. Capped at 50 results.
    2. predict_seasonal_demand(sku: str): Predicts 6-month seasonal demand for a given SKU.
    
    Behavioral Guidelines:
    1. ALWAYS execute queries using execute_dynamic_query when data from the database is needed. Do not guess.
    2. Format results into beautiful Markdown tables with headers (not raw JSON).
    3. Present the user with clear explanations of what you queried.
    4. If the database returns empty results, state that no records were found.
    5. Always be polite, professional, and explain your analytical findings.
    """
    
    contents = []
    for msg in history:
        contents.append(types.Content(
            role="user" if msg.role == "user" else "model",
            parts=[types.Part.from_text(text=msg.content)]
        ))
    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message)]
    ))
    
    tool_map = {
        "execute_dynamic_query": execute_dynamic_query,
        "predict_seasonal_demand": predict_seasonal_demand
    }
    
    for _ in range(8):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=[execute_dynamic_query, predict_seasonal_demand]
                )
            )
        except Exception as e:
            return f"Error executing Data Analyst: {e}"
            
        if not response.function_calls:
            return response.text if response.text else "Analysis complete."
            
        contents.append(response.candidates[0].content)
        
        tool_parts = []
        for call in response.function_calls:
            func_name = call.name
            args = call.args
            
            if func_name in tool_map:
                try:
                    result = tool_map[func_name](**args)
                except Exception as e:
                    result = f"Error running tool: {e}"
            else:
                result = f"Error: Tool '{func_name}' is not registered."
                
            tool_parts.append(
                types.Part.from_function_response(
                    name=func_name,
                    response={"result": result}
                )
            )
            
        contents.append(types.Content(
            role="tool",
            parts=tool_parts
        ))
        
    return "Error: Maximum tool execution depth reached without resolving query."


def run_operations_agent(user_message: str, history: List[MessageModel], provider_key: Optional[str] = None) -> str:
    try:
        client = get_gemini_client(provider_key)
    except Exception as e:
        return f"Gemini client initialization failed: {e}"
        
    system_instruction = """
    You are the D2C Operations Agent.
    Your role is to handle operational actions, specifically ordering new stock or creating purchase orders.
    You have access to the `create_purchase_order` tool.
    
    Your Available Tools:
    1. create_purchase_order(sku: str, quantity: int): Places a purchase order in the MongoDB database.
    
    Guidelines:
    1. When the user requests a purchase order or restocks inventory, extract the SKU and quantity and call the create_purchase_order tool.
    2. Respond with details about the created purchase order (e.g. PO ID, SKU, product name, total cost, and warehouse location) in a clean markdown table.
    3. Do NOT make up information.
    4. If the SKU is not specified, ask the user to clarify.
    5. Always be direct, clear, and professional.
    """
    
    contents = []
    for msg in history:
        contents.append(types.Content(
            role="user" if msg.role == "user" else "model",
            parts=[types.Part.from_text(text=msg.content)]
        ))
    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message)]
    ))
    
    tool_map = {
        "create_purchase_order": create_purchase_order
    }
    
    for _ in range(5):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=[create_purchase_order]
                )
            )
        except Exception as e:
            return f"Error executing Operations: {e}"
            
        if not response.function_calls:
            return response.text if response.text else "Operation complete."
            
        contents.append(response.candidates[0].content)
        
        tool_parts = []
        for call in response.function_calls:
            func_name = call.name
            args = call.args
            
            if func_name in tool_map:
                try:
                    result = tool_map[func_name](**args)
                except Exception as e:
                    result = f"Error running tool: {e}"
            else:
                result = f"Error: Tool '{func_name}' is not registered."
                
            tool_parts.append(
                types.Part.from_function_response(
                    name=func_name,
                    response={"result": result}
                )
            )
            
        contents.append(types.Content(
            role="tool",
            parts=tool_parts
        ))
        
    return "Error: Maximum tool execution depth reached without completing operation."


def run_general_agent(user_message: str, history: List[MessageModel], provider_key: Optional[str] = None) -> str:
    try:
        client = get_gemini_client(provider_key)
    except Exception as e:
        return f"Gemini client initialization failed: {e}"
        
    system_instruction = """
    You are the D2C Operations Supervisor.
    You are professional, elite, and greet the user warmly.
    
    Your role is to introduce the system, help route inquiries, and handle general questions.
    Explain that the application has:
    1. A Data Analyst Agent: Can query inventory, orders, customers, and perform sales breakdowns, as well as model seasonal demand forecasts.
    2. An Operations Agent: Can create and place purchase orders to restock inventory.
    
    Keep your reply concise and invite them to run an analysis or place an order.
    """
    
    contents = []
    for msg in history:
        contents.append(types.Content(
            role="user" if msg.role == "user" else "model",
            parts=[types.Part.from_text(text=msg.content)]
        ))
    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message)]
    ))
    
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction
            )
        )
        return response.text if response.text else "System online. How can I help you?"
    except Exception as e:
        return f"Error executing Supervisor: {e}"

# ----------------- Auth & History Endpoints -----------------

@app.post("/api/auth/login")
async def login_endpoint(login_req: LoginRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database is offline.")
        
    try:
        # Check if user already exists
        existing_user = db["Users"].find_one({"email": login_req.email})
        if existing_user:
            return {
                "user_id": existing_user["user_id"],
                "email": existing_user["email"],
                "name": existing_user["name"],
                "provider": existing_user["provider"],
                "token": f"mock-token-{existing_user['user_id']}"
            }
            
        # Create new user
        new_id = f"USR-{random.randint(10000, 99999)}"
        user_doc = {
            "user_id": new_id,
            "email": login_req.email,
            "name": login_req.name,
            "provider": login_req.provider,
            "created_at": datetime.datetime.now()
        }
        db["Users"].insert_one(user_doc)
        
        # Save back to local JSON if mock database is active
        if use_mock_db:
            mock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_db")
            os.makedirs(mock_dir, exist_ok=True)
            with open(os.path.join(mock_dir, "Users.json"), "w", encoding="utf-8") as f:
                f.write(json_util.dumps(list(db["Users"].find()), indent=2))
                
        return {
            "user_id": new_id,
            "email": login_req.email,
            "name": login_req.name,
            "provider": login_req.provider,
            "token": f"mock-token-{new_id}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication error: {e}")


@app.get("/api/conversations")
async def get_conversations(user_id: str):
    if db is None:
        return []
    try:
        convs = list(db["Conversations"].find({"user_id": user_id}).sort("updated_at", -1))
        return json.loads(json_util.dumps(convs))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch conversations: {e}")


@app.post("/api/conversations")
async def save_conversation(conv: ConversationModel):
    if db is None:
        raise HTTPException(status_code=500, detail="Database offline.")
    try:
        conv_doc = conv.dict()
        conv_doc["updated_at"] = datetime.datetime.now()
        
        db["Conversations"].update_one(
            {"conversation_id": conv.conversation_id},
            {"$set": conv_doc},
            upsert=True
        )
        
        if use_mock_db:
            mock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_db")
            os.makedirs(mock_dir, exist_ok=True)
            with open(os.path.join(mock_dir, "Conversations.json"), "w", encoding="utf-8") as f:
                f.write(json_util.dumps(list(db["Conversations"].find()), indent=2))
                
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save conversation: {e}")


@app.put("/api/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, rename_req: RenameRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database offline.")
    try:
        result = db["Conversations"].update_one(
            {"conversation_id": conversation_id},
            {"$set": {"title": rename_req.title, "updated_at": datetime.datetime.now()}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Conversation not found.")
            
        if use_mock_db:
            mock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_db")
            with open(os.path.join(mock_dir, "Conversations.json"), "w", encoding="utf-8") as f:
                f.write(json_util.dumps(list(db["Conversations"].find()), indent=2))
                
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to rename conversation: {e}")


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database offline.")
    try:
        result = db["Conversations"].delete_one({"conversation_id": conversation_id})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Conversation not found.")
            
        if use_mock_db:
            mock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_db")
            with open(os.path.join(mock_dir, "Conversations.json"), "w", encoding="utf-8") as f:
                f.write(json_util.dumps(list(db["Conversations"].find()), indent=2))
                
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete conversation: {e}")

# ----------------- Chat Endpoint -----------------

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    fastapi_request: Request,
    x_provider_key: Optional[str] = Header(None, alias="X-Provider-Key")
):
    ip = fastapi_request.client.host
    check_rate_limit(ip)
    
    user_msg = request.message
    history = request.history
    
    # 1. Supervisor routes using proxy key or header key
    route = route_request(user_msg, history, x_provider_key)
    print(f"Supervisor routed request to: {route}")
    
    # 2. Call sub-agent
    if route == "ANALYTICAL":
        reply = run_data_analyst(user_msg, history, x_provider_key)
    elif route == "OPERATIONAL":
        reply = run_operations_agent(user_msg, history, x_provider_key)
    else:
        reply = run_general_agent(user_msg, history, x_provider_key)
        
    # Log usage to MongoDB for monitoring & abuse prevention
    if db is not None:
        try:
            log_doc = {
                "ip": ip,
                "timestamp": datetime.datetime.now(),
                "estimated_tokens": (len(user_msg) + len(reply)) // 4,
                "agent_route": route,
                "user_id": request.user_id
            }
            db["UsageLogs"].insert_one(log_doc)
            
            if use_mock_db:
                mock_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mock_db")
                os.makedirs(mock_dir, exist_ok=True)
                with open(os.path.join(mock_dir, "UsageLogs.json"), "w", encoding="utf-8") as f:
                    f.write(json_util.dumps(list(db["UsageLogs"].find()), indent=2))
        except Exception as log_err:
            print(f"Failed to log usage: {log_err}")
            
    return ChatResponse(agent_reply=reply, route=route)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)