from flask import Flask, render_template, request, redirect, url_for, flash
import os
from config import Config
from llm_service import GeminiService

app = Flask(__name__)
app.config.from_object(Config)

# Initialize your Gemini Service
gemini_service = GeminiService(api_key=app.config['GEMINI_API_KEY'])

# Directory to save uploaded files temporarily
UPLOAD_FOLDER = 'instance/uploads' # Make sure 'instance' directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload_assignment', methods=['GET', 'POST'])
def upload_assignment():
    if request.method == 'POST':
        # Professor's Solution File Upload
        if 'solution_file' not in request.files:
            flash('No solution file part')
            return redirect(request.url)
        solution_file = request.files['solution_file']
        if solution_file.filename == '':
            flash('No selected solution file')
            return redirect(request.url)

        if solution_file:
            solution_filename = secure_filename(solution_file.filename)
            solution_path = os.path.join(app.config['UPLOAD_FOLDER'], solution_filename)
            solution_file.save(solution_path)
            flash('Solution file uploaded successfully!')

            # For hackathon, let's assume we immediately process a dummy student file
            # In a real app, this would be a separate student upload route
            # For demonstration: assume a student_submission.pdf is also uploaded or hardcoded for now
            dummy_student_submission_path = os.path.join(app.config['UPLOAD_FOLDER'], 'student_submission.pdf')
            # You'd need to handle actual student uploads here

            # --- LLM Integration ---
            try:
                # This is where you call your LLM service
                feedback = gemini_service.get_assignment_feedback(
                    student_submission_pdf_path=dummy_student_submission_path, # Replace with actual student file path
                    professor_solution_pdf_path=solution_path,
                    course_name="Introduction to Calculus"
                )
                flash(f"LLM Feedback Generated: {feedback[:200]}...") # Show a snippet
                # You would save this feedback to your database (models.py) and associate it with student/assignment
            except Exception as e:
                flash(f"Error during LLM processing: {e}")
            finally:
                # Clean up uploaded files after processing if they are temporary
                # os.remove(solution_path)
                # os.remove(dummy_student_submission_path) # If it was a temp file

                return render_template('upload_success.html', feedback=feedback) # Or redirect to a feedback page

    return render_template('upload_form.html') # A form to upload professor's solution and maybe student's

# Helper for secure filename (from werkzeug.utils)
from werkzeug.utils import secure_filename

# If you want to use the integrity check
@app.route('/check_integrity/<student_id>')
def check_integrity(student_id):
    # Retrieve student's submission path from DB
    student_submission_path = os.path.join(app.config['UPLOAD_FOLDER'], f'student_{student_id}_submission.pdf')
    if not os.path.exists(student_submission_path):
        flash("Student submission not found.")
        return redirect(url_for('index'))

    integrity_report = gemini_service.perform_integrity_check(student_submission_path)
    return render_template('integrity_report.html', report=integrity_report)

# For class insights, you'd collect all student reports first and then call:
@app.route('/class_insights')
def class_insights():
    # In a real app, retrieve all student feedback reports from your database
    # For demo:
    sample_reports = [
        "Student A struggled with derivatives, good on integrals.",
        "Student B aced everything, very few errors.",
        "Student C confused chain rule with product rule.",
        # ... more reports
    ]
    if not sample_reports:
        flash("No student reports available for insights.")
        return redirect(url_for('index'))

    overall_insights = gemini_service.get_class_performance_summary(sample_reports)
    return render_template('class_insights.html', insights=overall_insights)

if __name__ == '__main__':
    # You'll need to create some basic templates: index.html, upload_form.html, upload_success.html, integrity_report.html, class_insights.html
    # For local development
    app.run(debug=True)