import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from patent_agent.api.routers import analysis, stream, edits, chat

load_dotenv()

app = FastAPI(title="Patent Agent API", version="0.1.0")

origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis.router)
app.include_router(stream.router)
app.include_router(edits.router)
app.include_router(chat.router)
