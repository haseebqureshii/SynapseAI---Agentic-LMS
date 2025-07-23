from flask import app, request, jsonify, g
from functools import wraps
from models import User, db

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"message": "Authentication required: Missing X-API-Key header"}), 401
        user = User.query.filter_by(api_key=api_key).first()
        if not user:
            return jsonify({"message": "Invalid API Key"}), 403 # Changed to 403 for invalid key
        g.current_user = user # Store the authenticated user in Flask's global context
        return f(*args, **kwargs)
    return decorated_function

# Example route to generate API key (could be master-only or after initial email-based registration)
@app.route('/api/generate-key', methods=['POST'])
@require_api_key # Or a different auth for this specific endpoint
def generate_user_api_key():
    user = g.current_user
    if not user.api_key:
        user.generate_api_key()
        db.session.commit()
    return jsonify({'api_key': user.api_key}), 200