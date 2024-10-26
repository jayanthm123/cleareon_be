from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config import Config

engine = create_engine(Config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)