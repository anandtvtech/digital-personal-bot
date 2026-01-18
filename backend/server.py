from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from dotenv import load_dotenv
from typing import Optional, List, Dict
import json
import uuid
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from context import prompt

# Load env
load_dotenv()

app = FastAPI()

# ----------------------------
# CORS
# ----------------------------
origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ----------------------------
# AWS Bedrock Client
# ----------------------------
bedrock_client = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
)

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")

# ----------------------------
# Memory: S3 or Local
# ----------------------------
USE_S3 = os.getenv("USE_S3", "false").lower() == "true"
S3_BUCKET = os.getenv("S3_BUCKET", "")
MEMORY_DIR = os.getenv("MEMORY_DIR", "../memory")

if USE_S3:
    s3_client = boto3.client("s3")


# ----------------------------
# Pydantic Models
# ----------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


class Message(BaseModel):
    role: str
    content: str
    timestamp: str


# ----------------------------
# Memory Helpers
# ----------------------------
def get_memory_path(session_id: str) -> str:
    return f"{session_id}.json"


def load_conversation(session_id: str) -> List[Dict]:
    """Load conversation history from S3 or local"""
    if USE_S3:
        try:
            response = s3_client.get_object(
                Bucket=S3_BUCKET, Key=get_memory_path(session_id)
            )
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return []
            raise
    else:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        file_path = os.path.join(MEMORY_DIR, get_memory_path(session_id))

        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                return json.load(f)
        return []


def save_conversation(session_id: str, messages: List[Dict]):
    """Save conversation to S3 or local"""
    if USE_S3:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=get_memory_path(session_id),
            Body=json.dumps(messages, indent=2),
            ContentType="application/json",
        )
    else:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        file_path = os.path.join(MEMORY_DIR, get_memory_path(session_id))
        with open(file_path, "w") as f:
            json.dump(messages, f, indent=2)


# ----------------------------
# Bedrock Wrapper (Correct Nova Format)
# ----------------------------
def call_bedrock(conversation: List[Dict], user_message: str) -> str:
    """Call AWS Bedrock Nova using correct message formatting"""

    messages = []

    # Add conversation history (Nova only allows user/assistant)
    for msg in conversation[-20:]:
        messages.append({
            "role": msg["role"],  # must be "user" or "assistant"
            "content": [{"text": msg["content"]}]
        })

    # Add current user message
    messages.append({
        "role": "user",
        "content": [{"text": user_message}]
    })

    try:
        response = bedrock_client.converse(
            modelId=BEDROCK_MODEL_ID,

            # ✅ System prompt (NOT allowed inside messages)
            system=[{"text": prompt()}],

            messages=messages,

            inferenceConfig={
                "maxTokens": 2000,
                "temperature": 0.7,
                "topP": 0.9
            }
        )

        return response["output"]["message"]["content"][0]["text"]

    except ClientError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------
# API Routes
# ----------------------------
@app.get("/")
async def root():
    return {
        "message": "AI Digital Twin API (Bedrock Nova)",
        "memory": "S3" if USE_S3 else "local",
        "model": BEDROCK_MODEL_ID
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": BEDROCK_MODEL_ID,
        "use_s3": USE_S3
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):

    session_id = request.session_id or str(uuid.uuid4())

    # Load memory
    conversation = load_conversation(session_id)

    # Call Bedrock
    assistant_reply = call_bedrock(conversation, request.message)

    # Save both user + assistant messages
    conversation.append({
        "role": "user",
        "content": request.message,
        "timestamp": datetime.now().isoformat()
    })
    conversation.append({
        "role": "assistant",
        "content": assistant_reply,
        "timestamp": datetime.now().isoformat()
    })

    save_conversation(session_id, conversation)

    return ChatResponse(response=assistant_reply, session_id=session_id)


@app.get("/conversation/{session_id}")
async def get_conversation(session_id: str):
    return {
        "session_id": session_id,
        "messages": load_conversation(session_id)
    }


# ----------------------------
# Local development server
# ----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
