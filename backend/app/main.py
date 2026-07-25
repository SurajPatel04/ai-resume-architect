from contextlib import asynccontextmanager
import os
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.db import dispose_engine
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.utils.llm import get_openai_llm

from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.graphs.graph import workflow

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    app.state.llm = get_openai_llm()
    
    # Initialize Postgres checkpointer connection pool
    # psycopg expects standard postgresql:// not postgresql+asyncpg://
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    pool = AsyncConnectionPool(
        conninfo=db_url,
        max_size=20,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    # Wait for pool initialization
    await pool.wait()
    
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    
    app.state.graph = workflow.compile(checkpointer=checkpointer)
    app.state.checkpointer_pool = pool
    
    yield
    # Shutdown
    await dispose_engine()
    await pool.close()

app = FastAPI(lifespan=lifespan)

# Set up CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Set to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directory for PDFs
pdf_dir = os.path.join(os.path.dirname(__file__), "static", "pdfs")
os.makedirs(pdf_dir, exist_ok=True)
app.mount("/pdfs", StaticFiles(directory=pdf_dir), name="pdfs")

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(chat_router)

app.include_router(api_v1_router)

@app.get("/")
def root():
    return {"message": "Welcome to AI Resume Architect API"}
