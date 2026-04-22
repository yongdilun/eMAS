from fastapi import FastAPI
from database import engine, Base
import models

app = FastAPI(title="Factory Operations Agent API")

@app.on_event("startup")
async def startup():
    # create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health():
    return {"status": "ok"}
