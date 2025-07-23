from flask_sqlalchemy import SQLAlchemy
import datetime
import secrets

from sqlalchemy import MetaData

# --- Define Naming Convention ---
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
# This metadata object will be passed to SQLAlchemy
metadata = MetaData(naming_convention=convention)

db = SQLAlchemy(metadata=metadata)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(128), unique=True, nullable=False)
    name = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(256), unique=True, nullable=False)
    role = db.Column(db.String(10), nullable=False)  # 'master' or 'pupil'
    spaces = db.relationship('Space', backref='master', lazy=True)
    submissions = db.relationship('Submission', backref='pupil', lazy=True)
    api_key = db.Column(db.String(64), unique=True, nullable=True) # Store API key for users/clients

    def generate_api_key(self):
        self.api_key = secrets.token_urlsafe(32) # Generates a random, URL-safe string

class Space(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unique_code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(256), nullable=False)
    master_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    members = db.relationship('SpaceMember', backref='space', lazy=True)
    assignments = db.relationship('Assignment', backref='space', lazy=True)

class SpaceMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    space_id = db.Column(db.Integer, db.ForeignKey('space.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    space_id = db.Column(db.Integer, db.ForeignKey('space.id'), nullable=False)
    title = db.Column(db.String(256), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.DateTime, nullable=True)
    solution_file_path = db.Column(db.String(512), nullable=True)
    submissions = db.relationship('Submission', backref='assignment', lazy=True)

class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    pupil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    file_path = db.Column(db.String(512), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    attempted = db.Column(db.Boolean, default=True)
    llm_feedback_report = db.Column(db.Text, nullable=True)
    integrity_flag = db.Column(db.String(50), nullable=True)
    llm_score = db.Column(db.Float, nullable=True)