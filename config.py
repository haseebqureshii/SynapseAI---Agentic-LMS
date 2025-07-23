import os
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a-very-secret-key' # Keep for Flask security
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///site.db'
    GEMINI_API_KEY = os.environ.get('GOOGLE_API_KEY') # Assuming GOOGLE_API_KEY in your .env
    UPLOAD_FOLDER = 'uploads_gcs_temp' # TODO: For production, you should not store files locally but stream them directly to/from GCS
    # You might also add GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME')