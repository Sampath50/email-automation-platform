from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)  # Super admin
    is_approved = db.Column(db.Boolean, default=False)  # Can use platform?
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class EmailCampaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    campaign_name = db.Column(db.String(200), nullable=False)
    csv_filename = db.Column(db.String(200))
    subject = db.Column(db.String(500))
    email_body = db.Column(db.Text)
    sender_email = db.Column(db.String(200))
    sender_password = db.Column(db.String(200))
    total_recipients = db.Column(db.Integer, default=0)
    sent_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

class EmailLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('email_campaign.id'))
    recipient_email = db.Column(db.String(200))
    recipient_name = db.Column(db.String(200))
    status = db.Column(db.String(50))
    error_message = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)