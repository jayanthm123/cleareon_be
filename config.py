from datetime import timedelta


class Config:
    JWT_SECRET_KEY = 'your-super-secret-key'  # Change this in production!
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=10)
    REDIS_URL = "redis://localhost:6379"
    DATABASE_URL = "postgresql://user:password@localhost:5432/dbname"
    MAX_LOGIN_ATTEMPTS = 5
    LOGIN_ATTEMPT_TIMEOUT = 300  # 5 minutes in seconds