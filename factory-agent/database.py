import os
from dotenv import load_dotenv
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

load_dotenv()

# Default to SQLite for the agent unless specified
# In production, this should match the Go backend database (e.g. MySQL)
DATABASE_URL = os.getenv("DATABASE_URL", "mysql+aiomysql://root:@localhost:3306/emas")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
