"""
WSGI entry point for production deployment (Render, gunicorn).
"""
from app import create_app
from scheduler import start_scheduler

application = create_app()
start_scheduler(application)
