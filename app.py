import os
from flask import Flask, jsonify, request, g
from flask_migrate import Migrate
from models import db, User, Space, SpaceMember, Assignment, Submission # Import all models needed
from datetime import datetime
from dotenv import load_dotenv
from config import Config # Assuming Config is in config.py
from sqlalchemy import MetaData # For naming convention
from google.cloud import storage # New: For Google Cloud Storage integration

load_dotenv()

# --- Define Naming Convention for SQLAlchemy ---
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
metadata = MetaData(naming_convention=convention)

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Ensure SECRET_KEY and SQLALCHEMY_DATABASE_URI are loaded from Config
# (They should be set in your config.py, not directly here if using Config object)
# app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') # Redundant if in Config
# app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL') # Redundant if in Config
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Good practice

# Initialize db and migrate with the app and custom metadata
db.init_app(app)
migrate = Migrate(app, db) # Initialize Migrate after db.init_app

# Print DB path for debugging (useful during development)
basedir = os.path.abspath(os.path.dirname(__file__))
print("CWD:", os.getcwd())
print("DB will live at:", os.path.join(basedir, 'instance', 'synapseai.sqlite'))

# --- LLM Service Initialization ---
# Import GeminiService after Config is loaded
from llm_service import GeminiService
gemini_service = GeminiService(api_key=app.config['GEMINI_API_KEY'])

# Directory for temporary local file storage before/after GCS upload/download.
# In a production setup, direct streaming to/from GCS is preferred to avoid local disk I/O.
# This UPLOAD_FOLDER is for temporary local storage before uploading to GCS.
app.config['UPLOAD_FOLDER'] = 'instance/temp_uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Allowed file extensions for pupil submissions and professor solutions
ALLOWED_FILE_EXTENSIONS = {'pdf', 'py', 'txt'}

def allowed_file(filename: str, allowed_extensions: set) -> bool:
    """Checks if a filename has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

# Helper for secure filename (from werkzeug.utils)
from werkzeug.utils import secure_filename

# --- API Key Authentication Decorator ---
def require_api_key(f):
    """
    Decorator to enforce API key authentication for endpoints.
    Assumes a User model with an 'api_key' field and 'role'.
    """
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return jsonify({"message": "Authentication required: Missing X-API-Key header"}), 401
        
        user = User.query.filter_by(api_key=api_key).first()
        if not user:
            return jsonify({"message": "Invalid API Key"}), 403 # 403 Forbidden for invalid credentials
        
        g.current_user = user # Store the authenticated user in Flask's global context
        return f(*args, **kwargs)
    return decorated_function

# --- API Endpoints ---

@app.route('/api/status', methods=['GET'])
def api_status():
    """Returns a simple status message to check if the API is running."""
    return jsonify({'status': 'API is running', 'version': '1.0'}), 200

@app.route('/api/generate-key', methods=['POST'])
@require_api_key
def generate_user_api_key():
    """
    Generates or retrieves an API key for the authenticated user.
    This endpoint is typically accessed by a user after an initial
    registration/login process (e.g., via a separate web UI or internal tool).
    """
    user = g.current_user
    if not user.api_key:
        user.generate_api_key() # Method from models.py User class
        db.session.commit()
        return jsonify({'message': 'API key generated successfully', 'api_key': user.api_key}), 200
    return jsonify({'message': 'User already has an API key', 'api_key': user.api_key}), 200

@app.route('/api/spaces', methods=['POST'])
@require_api_key
def create_space_api():
    """
    Creates a new learning space. Only accessible by 'master' users.
    Expects JSON input: {'name': 'Space Name'}
    """
    if g.current_user.role != 'master':
        return jsonify({'message': 'Access denied: Must be a master user'}), 403

    data = request.get_json() # Use get_json() for JSON body
    if not data or 'name' not in data:
        return jsonify({'message': 'Missing space name in request body'}, {'example_body': {'name': 'Introduction to AI'}}), 400

    name = data.get('name')
    code = os.urandom(4).hex() # Generate unique code for space
    
    space = Space(name=name, unique_code=code, master_id=g.current_user.id)
    db.session.add(space)
    db.session.commit()
    return jsonify({
        'message': 'Space created successfully',
        'space_id': space.id,
        'space_name': space.name,
        'unique_code': space.unique_code
    }), 201

@app.route('/api/master/dashboard', methods=['GET'])
@require_api_key
def master_dashboard_api():
    """
    Retrieves a list of spaces managed by the authenticated master user.
    """
    if g.current_user.role != 'master':
        return jsonify({'message': 'Access denied: Must be a master user'}), 403

    spaces = Space.query.filter_by(master_id=g.current_user.id).all()
    
    # Serialize spaces and their assignments for JSON output
    spaces_data = []
    for space in spaces:
        assignments_data = []
        for assignment in space.assignments: # Assuming 'assignments' relationship is defined in Space model
            assignments_data.append({
                'id': assignment.id,
                'title': assignment.title,
                'description': assignment.description,
                'due_date': assignment.due_date.isoformat() if assignment.due_date else None,
                'solution_file_path': assignment.solution_file_path
            })
        spaces_data.append({
            'id': space.id,
            'name': space.name,
            'unique_code': space.unique_code,
            'assignments': assignments_data
        })
    return jsonify({'spaces': spaces_data}), 200

@app.route('/api/pupil/dashboard', methods=['GET'])
@require_api_key
def pupil_dashboard_api():
    """
    Retrieves a list of spaces the authenticated pupil user is a member of.
    """
    if g.current_user.role != 'pupil':
        return jsonify({'message': 'Access denied: Must be a pupil user'}), 403

    membership = SpaceMember.query.filter_by(user_id=g.current_user.id).all()
    spaces_data = []
    for member in membership:
        space = member.space # Assuming 'space' relationship is defined in SpaceMember model
        assignments_data = []
        for assignment in space.assignments:
            # Check if pupil has submitted for this assignment
            submission = Submission.query.filter_by(assignment_id=assignment.id, pupil_id=g.current_user.id).first()
            assignments_data.append({
                'id': assignment.id,
                'title': assignment.title,
                'description': assignment.description,
                'due_date': assignment.due_date.isoformat() if assignment.due_date else None,
                'has_submitted': bool(submission),
                'submission_id': submission.id if submission else None
            })
        spaces_data.append({
            'id': space.id,
            'name': space.name,
            'unique_code': space.unique_code,
            'master_id': space.master_id,
            'assignments': assignments_data
        })
    return jsonify({'spaces': spaces_data}), 200

@app.route('/api/spaces/<int:space_id>', methods=['GET'])
@require_api_key
def get_space_detail_api(space_id):
    """
    Retrieves details for a specific space, including its assignments.
    Accessible by master (if they own it) or pupils (if they are members).
    """
    space = Space.query.get(space_id)
    if not space:
        return jsonify({'message': 'Space not found'}), 404

    # Authorization check: Master of the space OR a member of the space
    is_master = g.current_user.id == space.master_id
    is_member = SpaceMember.query.filter_by(space_id=space_id, user_id=g.current_user.id).first()
    if not is_master and not is_member:
        return jsonify({'message': 'Access denied to this space'}), 403

    assignments_data = []
    for assignment in space.assignments:
        assignments_data.append({
            'id': assignment.id,
            'title': assignment.title,
            'description': assignment.description,
            'due_date': assignment.due_date.isoformat() if assignment.due_date else None,
            'solution_file_path': assignment.solution_file_path
        })

    return jsonify({
        'id': space.id,
        'name': space.name,
        'unique_code': space.unique_code,
        'master_id': space.master_id,
        'assignments': assignments_data
    }), 200

@app.route('/api/spaces/<int:space_id>/assignments', methods=['POST'])
@require_api_key
def create_assignment_api(space_id):
    """
    Creates a new assignment within a specific space. Only accessible by the space's master.
    Expects multipart/form-data: 'title', 'description', 'due_date' (optional), 'solution' (file)
    """
    if g.current_user.role != 'master':
        return jsonify({'message': 'Access denied: Must be a master user'}), 403

    space = Space.query.get(space_id)
    if not space:
        return jsonify({'message': 'Space not found'}), 404
    
    if g.current_user.id != space.master_id:
        return jsonify({'message': 'Access denied: You are not the master of this space'}), 403

    title = request.form.get('title')
    description = request.form.get('description')
    due_date_str = request.form.get('due_date')
    solution_file = request.files.get('solution')

    if not title:
        return jsonify({'message': 'Missing assignment title'}), 400

    assignment = Assignment(space_id=space.id, title=title, description=description)
    if due_date_str:
        try:
            assignment.due_date = datetime.fromisoformat(due_date_str)
        except ValueError:
            return jsonify({'message': 'Invalid due date format. Use YYYY-MM-DDTHH:MM:SS format.'}), 400
    
    db.session.add(assignment)
    db.session.commit() # Commit to get assignment.id for filename

    if solution_file and allowed_file(solution_file.filename, ALLOWED_FILE_EXTENSIONS):
        try:
            # --- Placeholder for Google Cloud Storage Upload ---
            # In production, upload directly to GCS.
            # For now, saving locally as a temporary measure
            filename = secure_filename(solution_file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], f"solution_{assignment.id}_{filename}")
            solution_file.save(path)
            gcs_path = path # Placeholder: Treat local path as GCS path for now

            assignment.solution_file_path = gcs_path
            db.session.commit()
        except Exception as e:
            print(f"Error uploading solution file for assignment {assignment.id}: {e}")
            return jsonify({'error': f"An error occurred during solution file upload: {str(e)}"}), 500
    else:
        # If solution file is provided but invalid, or not provided, it's not a critical error
        # but you might want to log it or return a warning.
        pass # Assignment created even without a valid solution file

    return jsonify({
        'message': 'Assignment created successfully',
        'assignment_id': assignment.id,
        'title': assignment.title,
        'space_id': assignment.space_id,
        'solution_file_path': assignment.solution_file_path # Will be GCS path
    }), 201

@app.route('/api/assignments/<int:assignment_id>', methods=['PUT'])
@require_api_key
def edit_assignment_api(assignment_id):
    """
    Edits an existing assignment. Only accessible by the master of the space.
    Expects multipart/form-data: 'title', 'description', 'due_date' (optional), 'solution' (file, optional)
    """
    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({'message': 'Assignment not found'}), 404
    
    if g.current_user.role != 'master' or g.current_user.id != assignment.space.master_id:
        return jsonify({'message': 'Access denied: You are not authorized to edit this assignment'}), 403

    title = request.form.get('title')
    description = request.form.get('description')
    due_date_str = request.form.get('due_date')
    solution_file = request.files.get('solution')

    if title:
        assignment.title = title
    if description:
        assignment.description = description
    
    if due_date_str:
        try:
            assignment.due_date = datetime.fromisoformat(due_date_str)
        except ValueError:
            return jsonify({'message': 'Invalid due date format. Use YYYY-MM-DDTHH:MM:SS format.'}), 400
    elif due_date_str == '': # Allow clearing due date
        assignment.due_date = None

    if solution_file and allowed_file(solution_file.filename, ALLOWED_FILE_EXTENSIONS):
        try:
            # --- Placeholder for Google Cloud Storage Upload ---
            filename = secure_filename(solution_file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], f"solution_{assignment.id}_{filename}")
            solution_file.save(path)
            gcs_path = path # Placeholder: Treat local path as GCS path for now

            assignment.solution_file_path = gcs_path
        except Exception as e:
            print(f"Error uploading new solution file for assignment {assignment.id}: {e}")
            return jsonify({'error': f"An error occurred during new solution file upload: {str(e)}"}), 500
    elif solution_file is not None and solution_file.filename == '':
        # If an empty file input was sent, it means the user wants to clear the existing file
        assignment.solution_file_path = None

    db.session.commit()

    # Removed email notification as send_email is removed.
    # If notifications are needed, they would be handled by a separate service or client.

    return jsonify({
        'message': 'Assignment updated successfully',
        'assignment_id': assignment.id,
        'title': assignment.title,
        'description': assignment.description,
        'due_date': assignment.due_date.isoformat() if assignment.due_date else None,
        'solution_file_path': assignment.solution_file_path
    }), 200

@app.route('/api/assignments/<int:assignment_id>', methods=['DELETE'])
@require_api_key
def delete_assignment_api(assignment_id):
    """
    Deletes an assignment. Only accessible by the master of the space.
    """
    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({'message': 'Assignment not found'}), 404
    
    if g.current_user.role != 'master' or g.current_user.id != assignment.space.master_id:
        return jsonify({'message': 'Access denied: You are not authorized to delete this assignment'}), 403

    # Optionally, delete associated submissions and files from GCS
    # For submissions: Submission.query.filter_by(assignment_id=assignment_id).delete()
    # For GCS files: needs GCS client to delete blobs

    db.session.delete(assignment)
    db.session.commit()
    return jsonify({'message': 'Assignment deleted successfully'}), 204 # 204 No Content for successful deletion

@app.route('/api/spaces/join', methods=['POST'])
@require_api_key
def join_space_api():
    """
    Allows a pupil to join a space using a unique code.
    Expects JSON input: {'code': 'unique_code'}
    """
    if g.current_user.role != 'pupil':
        return jsonify({'message': 'Access denied: Only pupils can join spaces'}), 403

    data = request.get_json()
    if not data or 'code' not in data:
        return jsonify({'message': 'Missing space code in request body'}), 400

    code = data.get('code')
    space = Space.query.filter_by(unique_code=code).first()
    if not space:
        return jsonify({'message': 'Invalid space code'}), 404
    
    exists = SpaceMember.query.filter_by(space_id=space.id, user_id=g.current_user.id).first()
    if exists:
        return jsonify({'message': 'You are already a member of this space'}), 409 # 409 Conflict

    db.session.add(SpaceMember(space_id=space.id, user_id=g.current_user.id))
    db.session.commit()
    return jsonify({
        'message': 'Successfully joined space',
        'space_id': space.id,
        'space_name': space.name
    }), 200

@app.route('/api/assignments/<int:assignment_id>/submit', methods=['POST'])
@require_api_key
def submit_assignment_api(assignment_id):
    """
    Allows a pupil to submit their solution for an assignment.
    Expects multipart/form-data: 'file' (student's submission file)
    """
    if g.current_user.role != 'pupil':
        return jsonify({'message': 'Access denied: Only pupils can submit assignments'}), 403

    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({'message': 'Assignment not found'}), 404

    existing_submission = Submission.query.filter_by(assignment_id=assignment_id, pupil_id=g.current_user.id).first()
    if existing_submission:
        return jsonify({'message': 'You have already submitted this assignment'}), 409 # 409 Conflict

    student_file = request.files.get('file') # 'file' is the expected field name for the student's submission
    if not student_file or not allowed_file(student_file.filename, ALLOWED_FILE_EXTENSIONS):
        return jsonify({'message': 'Invalid or missing student submission file. Allowed types: pdf, py, txt'}), 400

    # --- Student Submission File Upload to GCS ---
    try:
        # Initialize GCS client here (or pass from app context)
        gcs_client = storage.Client()
        bucket_name = app.config.get('GCS_BUCKET_NAME') # Ensure this is set in config.py
        if not bucket_name:
            return jsonify({'error': 'GCS_BUCKET_NAME not configured in app config'}, 500)
        bucket = gcs_client.get_bucket(bucket_name)

        original_filename = secure_filename(student_file.filename)
        # Create a unique blob name in GCS
        gcs_blob_name = f"submissions/assignment_{assignment_id}/pupil_{g.current_user.id}/{original_filename}"
        blob = bucket.blob(gcs_blob_name)
        blob.upload_from_file(student_file) # Uploads the file stream directly to GCS
        gcs_file_path = f"gs://{bucket_name}/{gcs_blob_name}" # Store this in DB

        # --- Get Professor's Solution Path from DB ---
        professor_solution_gcs_path = assignment.solution_file_path
        if not professor_solution_gcs_path:
            # If no solution file, maybe allow submission but skip LLM analysis or return specific error
            return jsonify({'message': 'Professor solution not uploaded for this assignment, cannot generate feedback'}), 400

        # --- LLM Integration ---
        # Note: llm_service.py's _prepare_pdf_part needs to be updated to fetch from GCS URL
        feedback_report = gemini_service.get_assignment_feedback(
            student_submission_source=gcs_file_path, # This will be GCS path
            professor_solution_source=professor_solution_gcs_path, # This will be GCS path
            course_name=assignment.space.name # Assuming space relation is loaded
        )
        
        integrity_report_text = gemini_service.perform_integrity_check(
            student_submission_source=gcs_file_path
        )
        # Simple parsing for integrity flag (can be more sophisticated)
        integrity_flag = "review_needed" if "flag" in integrity_report_text.lower() or "concern" in integrity_report_text.lower() else "clear"

        # --- Save LLM results to Database ---
        submission = Submission(
            assignment_id=assignment.id,
            pupil_id=g.current_user.id,
            file_path=gcs_file_path,
            llm_feedback_report=feedback_report,
            integrity_flag=integrity_flag
            # llm_score (if LLM provides a numerical score, parse and store it)
        )
        db.session.add(submission)
        db.session.commit()

        return jsonify({
            'message': 'Submission successful and feedback generated',
            'submission_id': submission.id,
            'feedback_report': feedback_report,
            'integrity_check_summary': integrity_report_text,
            'integrity_flag': integrity_flag
        }), 201

    except Exception as e:
        # Log the error for debugging purposes
        print(f"Error during LLM processing for submission {assignment_id} by {g.current_user.id}: {e}")
        # Attempt to delete the partially uploaded GCS blob if an error occurred after upload
        try:
            if 'blob' in locals() and blob.exists():
                blob.delete()
                print(f"Cleaned up partial GCS upload: {gcs_blob_name}")
        except Exception as cleanup_e:
            print(f"Error during GCS cleanup: {cleanup_e}")
        return jsonify({'error': f"An error occurred during processing: {str(e)}"}), 500

@app.route('/api/assignments/<int:assignment_id>', methods=['GET'])
@require_api_key
def get_assignment_detail_api(assignment_id):
    """
    Retrieves details for a specific assignment.
    Accessible by master (if they own the space) or pupils (if they are members).
    If a pupil, also includes their submission details if available.
    """
    assignment = Assignment.query.get(assignment_id)
    if not assignment:
        return jsonify({'message': 'Assignment not found'}), 404

    # Authorization check: Master of the space OR a member of the space
    is_master_of_space = g.current_user.id == assignment.space.master_id
    is_member_of_space = SpaceMember.query.filter_by(space_id=assignment.space_id, user_id=g.current_user.id).first()
    
    if not is_master_of_space and not is_member_of_space:
        return jsonify({'message': 'Access denied to this assignment'}), 403

    response_data = {
        'id': assignment.id,
        'title': assignment.title,
        'description': assignment.description,
        'due_date': assignment.due_date.isoformat() if assignment.due_date else None,
        'solution_file_path': assignment.solution_file_path,
        'space_id': assignment.space_id,
        'space_name': assignment.space.name # Assuming space relation is loaded
    }

    submission_data = None
    if g.current_user.role == 'pupil':
        submission = Submission.query.filter_by(assignment_id=assignment_id, pupil_id=g.current_user.id).first()
        if submission:
            submission_data = {
                'submission_id': submission.id,
                'file_path': submission.file_path,
                'timestamp': submission.timestamp.isoformat(),
                'attempted': submission.attempted,
                'llm_feedback_report': submission.llm_feedback_report,
                'integrity_flag': submission.integrity_flag,
                'llm_score': submission.llm_score
            }
    response_data['my_submission'] = submission_data

    return jsonify(response_data), 200

@app.route('/api/submissions/<int:submission_id>/feedback', methods=['GET'])
@require_api_key
def get_submission_feedback_api(submission_id):
    """
    Retrieves the LLM-generated feedback for a specific submission.
    Accessible by the pupil who made the submission or the master of the space.
    """
    submission = Submission.query.get(submission_id)

    if not submission:
        return jsonify({'message': 'Submission not found'}), 404

    # Authorization check: Is the current user the pupil who submitted OR the master of the space?
    is_pupil = g.current_user.id == submission.pupil_id
    is_master = g.current_user.id == submission.assignment.space.master_id # Assuming relations are loaded
    
    if not is_pupil and not is_master:
        return jsonify({'message': 'Access denied to this submission feedback'}), 403

    return jsonify({
        'submission_id': submission.id,
        'assignment_id': submission.assignment_id,
        'pupil_id': submission.pupil_id,
        'feedback_report': submission.llm_feedback_report,
        'integrity_flag': submission.integrity_flag,
        'llm_score': submission.llm_score
    }), 200

@app.route('/api/class-insights/<int:space_id>', methods=['GET'])
@require_api_key
def get_class_insights_api(space_id):
    """
    Generates and retrieves consolidated LLM insights for all submissions
    within a specific space. Only accessible by the master of that space.
    """
    space = Space.query.get(space_id)
    if not space:
        return jsonify({'message': 'Space not found'}), 404

    if g.current_user.id != space.master_id:
        return jsonify({'message': 'Access denied: Only the master of this space can view class insights'}), 403

    # Retrieve all feedback reports for assignments within this space
    all_feedback_reports = []
    # Efficiently fetch submissions and assignments using joins to minimize DB queries
    submissions_in_space = Submission.query.join(Assignment).filter(Assignment.space_id == space_id).all()
    
    for submission in submissions_in_space:
        if submission.llm_feedback_report:
            # Include assignment title for better context in the summary prompt
            assignment_title = submission.assignment.title if submission.assignment else "Unknown Assignment"
            all_feedback_reports.append(f"Submission by Pupil ID {submission.pupil_id} for Assignment '{assignment_title}':\n{submission.llm_feedback_report}")

    if not all_feedback_reports:
        return jsonify({"message": "No student reports available for insights in this space."}), 200

    try:
        overall_insights = gemini_service.get_class_performance_summary(all_feedback_reports)
        return jsonify({
            'space_id': space.id,
            'space_name': space.name,
            'overall_class_insights': overall_insights
        }), 200
    except Exception as e:
        print(f"Error generating class insights: {e}")
        return jsonify({'error': f"An error occurred while generating class insights: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)