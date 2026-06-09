from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_required, login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import db, User, EmailCampaign, EmailLog
from email_handler import send_emails_async
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import threading

load_dotenv()

app = Flask(__name__, 
            template_folder='../frontend/templates',
            static_folder='../frontend/static')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///email_system.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ============= AUTO-CREATE DATABASE TABLES ON STARTUP =============
with app.app_context():
    db.create_all()
    print("✅ Database tables ready")
    
    # Create admin if doesn't exist
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123'),
            is_admin=True,
            is_approved=True
        )
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin user created!")
    else:
        print("✅ Admin user already exists")

# ============= PUBLIC ROUTES =============
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/create-db')
def create_db():
    """Manual database creation endpoint - visit this if database isn't working"""
    try:
        with app.app_context():
            db.create_all()
            
            # Create admin if doesn't exist
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                admin = User(
                    username='admin',
                    email='admin@example.com',
                    password_hash=generate_password_hash('admin123'),
                    is_admin=True,
                    is_approved=True
                )
                db.session.add(admin)
                db.session.commit()
                return """
                <h2>✅ Database Created Successfully!</h2>
                <p>Admin credentials:</p>
                <ul>
                    <li><strong>Username:</strong> admin</li>
                    <li><strong>Password:</strong> admin123</li>
                </ul>
                <br>
                <a href='/login'>Click here to login →</a>
                """
            else:
                return """
                <h2>✅ Database Already Exists!</h2>
                <p>Admin credentials:</p>
                <ul>
                    <li><strong>Username:</strong> admin</li>
                    <li><strong>Password:</strong> admin123</li>
                </ul>
                <br>
                <a href='/login'>Click here to login →</a>
                """
    except Exception as e:
        return f"<h2>❌ Error creating database:</h2><p>{str(e)}</p>"

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'danger')
            return redirect(url_for('register'))
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_admin=False,
            is_approved=False
        )
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Waiting for admin approval.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            if not user.is_approved and not user.is_admin:
                flash('Your account is pending admin approval!', 'warning')
                return redirect(url_for('login'))
            login_user(user)
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('user_dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ============= USER ROUTES =============
@app.route('/user-dashboard', methods=['GET', 'POST'])
@login_required
def user_dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    
    if not current_user.is_approved:
        flash('Your account is not approved yet!', 'danger')
        return redirect(url_for('logout'))
    
    if request.method == 'POST':
        # Get user's email credentials and campaign details
        sender_email = request.form['sender_email']
        sender_password = request.form['sender_password']
        subject = request.form['subject']
        email_body = request.form['email_body']
        file = request.files['csv_file']
        
        if file and file.filename.endswith('.csv'):
            filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            df = pd.read_csv(filepath)
            total_recipients = len(df)
            
            campaign = EmailCampaign(
                user_id=current_user.id,
                campaign_name=f"{current_user.username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                csv_filename=filename,
                subject=subject,
                email_body=email_body,
                sender_email=sender_email,
                sender_password=sender_password,  # In production, encrypt this!
                total_recipients=total_recipients,
                status='pending'
            )
            db.session.add(campaign)
            db.session.commit()
            
            smtp_config = {
                'server': 'smtp.gmail.com',
                'port': 587,
                'email': sender_email,
                'password': sender_password,
                'delay': 4
            }
            
            thread = threading.Thread(target=send_emails_async, args=(app, campaign.id, smtp_config, df))
            thread.start()
            
            flash('Email campaign started! You will see results in Campaign Logs.', 'success')
            return redirect(url_for('campaign_logs'))
    
    return render_template('user_dashboard.html')

@app.route('/campaign-logs')
@login_required
def campaign_logs():
    if current_user.is_admin:
        campaigns = EmailCampaign.query.order_by(EmailCampaign.created_at.desc()).all()
    else:
        campaigns = EmailCampaign.query.filter_by(user_id=current_user.id).order_by(EmailCampaign.created_at.desc()).all()
    return render_template('campaign_logs.html', campaigns=campaigns)

@app.route('/view-logs/<int:campaign_id>')
@login_required
def view_logs(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    if not current_user.is_admin and campaign.user_id != current_user.id:
        flash('Unauthorized!', 'danger')
        return redirect(url_for('campaign_logs'))
    
    logs = EmailLog.query.filter_by(campaign_id=campaign_id).order_by(EmailLog.sent_at.desc()).all()
    return render_template('view_logs.html', campaign=campaign, logs=logs)

# ============= ADMIN ROUTES =============
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('user_dashboard'))
    
    pending_users = User.query.filter_by(is_approved=False, is_admin=False).all()
    approved_users = User.query.filter_by(is_approved=True, is_admin=False).all()
    all_campaigns = EmailCampaign.query.order_by(EmailCampaign.created_at.desc()).limit(50).all()
    
    return render_template('admin_dashboard.html', 
                         pending_users=pending_users, 
                         approved_users=approved_users,
                         campaigns=all_campaigns)

@app.route('/approve-user/<int:user_id>')
@login_required
def approve_user(user_id):
    if not current_user.is_admin:
        flash('Unauthorized!', 'danger')
        return redirect(url_for('user_dashboard'))
    
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    flash(f'User {user.username} has been approved!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/reject-user/<int:user_id>')
@login_required
def reject_user(user_id):
    if not current_user.is_admin:
        flash('Unauthorized!', 'danger')
        return redirect(url_for('user_dashboard'))
    
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} has been rejected.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/setup')
def setup():
    admin = User.query.filter_by(is_admin=True).first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123'),
            is_admin=True,
            is_approved=True
        )
        db.session.add(admin)
        db.session.commit()
        return "Admin created! Username: admin, Password: admin123"
    return "Admin already exists!"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)