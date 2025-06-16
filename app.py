import os
from flask import Flask, redirect, url_for, session, render_template, request, flash
from models import db, User, Space, SpaceMember, Assignment, Submission
from requests_oauthlib import OAuth2Session
from dotenv import load_dotenv

import os

load_dotenv()

# WARNING: only for local dev!
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

basedir = os.path.abspath(os.path.dirname(__file__))
print("CWD:", os.getcwd())
print("DB will live at:", os.path.join(basedir, 'instance', 'synapseai.sqlite'))

db.init_app(app)

# OAuth2 client setup
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_DISCOVERY_URL = os.getenv('GOOGLE_DISCOVERY_URL')

# Utility to get Google provider configuration
import requests

def get_google_provider_cfg():
    return requests.get(GOOGLE_DISCOVERY_URL).json()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login():
    google = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=url_for('authorize', _external=True), scope=['openid', 'email', 'profile'])
    authorization_url, state = google.authorization_url(get_google_provider_cfg()['authorization_endpoint'], access_type='offline', prompt='consent')
    session['oauth_state'] = state
    return redirect(authorization_url)

@app.route('/authorize')
def authorize():
    google = OAuth2Session(GOOGLE_CLIENT_ID, state=session['oauth_state'], redirect_uri=url_for('authorize', _external=True))
    token = google.fetch_token(get_google_provider_cfg()['token_endpoint'], client_secret=GOOGLE_CLIENT_SECRET, authorization_response=request.url)
    session['oauth_token'] = token

    # Fetch user info
    userinfo = google.get(get_google_provider_cfg()['userinfo_endpoint']).json()
    google_id = userinfo['sub']
    email = userinfo['email']
    name = userinfo.get('name', '')

    emails = os.getenv('MASTER_EMAILS', '').split(',')
    role = 'master' if email in emails else 'pupil'

    user = User(google_id=google_id, name=name, email=email, role=role)

    # Create or get user
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        # Default role assignment logic can be improved later
        user = User(google_id=google_id, name=name, email=email, role=role)
        db.session.add(user)
        db.session.commit()
    session['user_id'] = user.id
    session['role'] = user.role

    # Redirect based on role
    if user.role == 'master':
        return redirect(url_for('master_dashboard'))
    return redirect(url_for('pupil_dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('index'))

@app.route('/master_dashboard')
def master_dashboard():
    if session.get('role') != 'master':
        flash('Access denied.')
        return redirect(url_for('index'))
    user = User.query.get(session['user_id'])
    spaces = Space.query.filter_by(master_id=user.id).all()
    return render_template('master_dashboard.html', spaces=spaces)

@app.route('/pupil_dashboard')
def pupil_dashboard():
    if session.get('role') != 'pupil':
        flash('Access denied.')
        return redirect(url_for('index'))
    user = User.query.get(session['user_id'])
    membership = SpaceMember.query.filter_by(user_id=user.id).all()
    spaces = [m.space for m in membership]
    return render_template('pupil_dashboard.html', spaces=spaces)

@app.route('/create_space', methods=['POST'])
def create_space():
    if session.get('role') != 'master':
        flash('Access denied.')
        return redirect(url_for('index'))
    name = request.form.get('name')
    code = os.urandom(4).hex()
    space = Space(name=name, unique_code=code, master_id=session['user_id'])
    db.session.add(space)
    db.session.commit()
    return redirect(url_for('master_dashboard'))

@app.route('/join_space', methods=['POST'])
def join_space():
    if session.get('role') != 'pupil':
        flash('Access denied.')
        return redirect(url_for('index'))
    code = request.form.get('code')
    space = Space.query.filter_by(unique_code=code).first()
    if not space:
        flash('Invalid code.')
        return redirect(url_for('pupil_dashboard'))
    exists = SpaceMember.query.filter_by(space_id=space.id, user_id=session['user_id']).first()
    if not exists:
        db.session.add(SpaceMember(space_id=space.id, user_id=session['user_id']))
        db.session.commit()
    return redirect(url_for('pupil_dashboard'))

@app.route('/submit_assignment/<int:assignment_id>', methods=['POST'])
def submit_assignment(assignment_id):
    if session.get('role') != 'pupil':
        flash('Access denied.')
        return redirect(url_for('index'))
    user_id = session['user_id']
    existing = Submission.query.filter_by(assignment_id=assignment_id, pupil_id=user_id).first()
    if existing:
        flash('You have already submitted this assignment.')
        return redirect(url_for('assignment_detail', assignment_id=assignment_id))
    file = request.files.get('file')
    if not file:
        flash('No file uploaded.')
        return redirect(url_for('assignment_detail', assignment_id=assignment_id))
    filename = f"sub_{assignment_id}_{user_id}_{file.filename}"
    path = os.path.join('uploads', filename)
    os.makedirs('uploads', exist_ok=True)
    file.save(path)
    submission = Submission(assignment_id=assignment_id, pupil_id=user_id, file_path=path, attempted=True)
    db.session.add(submission)
    db.session.commit()
    flash('Submission successful.')
    return redirect(url_for('assignment_detail', assignment_id=assignment_id))

@app.route('/assignment/<int:assignment_id>')
def assignment_detail(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    submission = None
    if session.get('role') == 'pupil':
        submission = Submission.query.filter_by(assignment_id=assignment_id, pupil_id=session['user_id']).first()
    return render_template('assignment_detail.html', assignment=assignment, submission=submission)

if __name__ == '__main__':
    app.run(debug=True)