from app import app, db
from database import User, EmailCampaign, EmailLog
from werkzeug.security import generate_password_hash

with app.app_context():
    # Drop all tables
    db.drop_all()
    print("Dropped all tables")
    
    # Create all tables
    db.create_all()
    print("Created all tables")
    
    # Check if columns exist
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('user')]
    print(f"Columns in user table: {columns}")
    
    # Create admin user
    admin = User(
        username='admin',
        email='admin@example.com',
        password_hash=generate_password_hash('admin123'),
        is_admin=True,
        is_approved=True
    )
    db.session.add(admin)
    db.session.commit()
    print("Admin created successfully!")
    print("Username: admin, Password: admin123")

print("Done!")