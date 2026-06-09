from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
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
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ============= PUBLIC ROUTES =============
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists!', 'danger')
            return redirect(url_for('register'))
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_super_admin=False,
            is_approved=False
        )
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Wait for admin approval.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            if not user.is_approved and not user.is_super_admin:
                flash('Your account is pending admin approval!', 'warning')
                return redirect(url_for('login'))
            login_user(user)
            if user.is_super_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('send_email'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ============= USER ROUTES =============
@app.route('/send-email', methods=['GET', 'POST'])
@login_required
def send_email():
    if current_user.is_super_admin:
        return redirect(url_for('admin_dashboard'))
    
    if not current_user.is_approved:
        flash('Your account is not approved yet!', 'danger')
        return redirect(url_for('logout'))
    
    if request.method == 'POST':
        email_address = request.form['email_address']
        email_password = request.form['email_password']
        subject = request.form['subject']
        email_body = request.form['email_body']
        file = request.files['csv_file']
        
        current_user.email_address = email_address
        current_user.email_password = email_password
        db.session.commit()
        
        if file and file.filename.endswith('.csv'):
            filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            df = pd.read_csv(filepath)
            total_recipients = len(df)
            
            campaign = EmailCampaign(
                user_id=current_user.id,
                campaign_name=f"Campaign_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                csv_filename=filename,
                subject=subject,
                email_body=email_body,
                total_recipients=total_recipients,
                status='pending'
            )
            db.session.add(campaign)
            db.session.commit()
            
            smtp_config = {
                'server': current_user.smtp_server or 'smtp.gmail.com',
                'port': current_user.smtp_port or 587,
                'email': email_address,
                'password': email_password,
                'delay': 4
            }
            
            thread = threading.Thread(target=send_emails_async, args=(app, campaign.id, smtp_config, df))
            thread.start()
            
            flash('Email campaign started! Check logs for progress.', 'success')
            return redirect(url_for('campaign_logs'))
    
    return render_template('send_email.html')

@app.route('/campaign-logs')
@login_required
def campaign_logs():
    if current_user.is_super_admin:
        campaigns = EmailCampaign.query.order_by(EmailCampaign.created_at.desc()).all()
    else:
        campaigns = EmailCampaign.query.filter_by(user_id=current_user.id).order_by(EmailCampaign.created_at.desc()).all()
    return render_template('campaign_logs.html', campaigns=campaigns)

# ============= THIS IS THE ROUTE YOU NEED TO ADD =============
@app.route('/view-logs/<int:campaign_id>')
@login_required
def view_logs(campaign_id):
    campaign = EmailCampaign.query.get_or_404(campaign_id)
    
    # Check if user has permission to view this campaign
    if not current_user.is_super_admin and campaign.user_id != current_user.id:
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('campaign_logs'))
    
    logs = EmailLog.query.filter_by(campaign_id=campaign_id).order_by(EmailLog.sent_at.desc()).all()
    return render_template('view_logs.html', campaign=campaign, logs=logs)
# ============= END OF ADDED ROUTE =============

# ============= SUPER ADMIN ROUTES =============
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_super_admin:
        flash('Unauthorized access!', 'danger')
        return redirect(url_for('send_email'))
    
    pending_users = User.query.filter_by(is_approved=False, is_super_admin=False).all()
    approved_users = User.query.filter_by(is_approved=True, is_super_admin=False).all()
    all_campaigns = EmailCampaign.query.order_by(EmailCampaign.created_at.desc()).limit(50).all()
    
    return render_template('admin_dashboard.html', 
                         pending_users=pending_users, 
                         approved_users=approved_users,
                         campaigns=all_campaigns)

@app.route('/approve-user/<int:user_id>')
@login_required
def approve_user(user_id):
    if not current_user.is_super_admin:
        flash('Unauthorized!', 'danger')
        return redirect(url_for('send_email'))
    
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    flash(f'User {user.username} has been approved!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/reject-user/<int:user_id>')
@login_required
def reject_user(user_id):
    if not current_user.is_super_admin:
        flash('Unauthorized!', 'danger')
        return redirect(url_for('send_email'))
    
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} has been rejected and removed.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/setup')
def setup():
    admin = User.query.filter_by(username='superadmin').first()
    if not admin:
        admin = User(
            username='superadmin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123'),
            is_super_admin=True,
            is_approved=True
        )
        db.session.add(admin)
        db.session.commit()
        return "Super Admin created! Username: superadmin, Password: admin123"
    return "Super Admin already exists!"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)