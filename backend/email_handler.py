import smtplib
import pandas as pd
import unicodedata
import re
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from database import db, EmailCampaign, EmailLog
import sys

def clean_email(raw):
    if pd.isna(raw):
        return ""
    raw = unicodedata.normalize("NFKD", str(raw))
    raw = raw.encode("ascii", "ignore").decode()
    raw = raw.replace(" ", "").strip()
    return raw

def is_valid_email(email):
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None

def send_emails_async(app, campaign_id, smtp_config, email_data):
    with app.app_context():
        campaign = EmailCampaign.query.get(campaign_id)
        
        print(f"=== STARTING CAMPAIGN {campaign_id} ===", file=sys.stderr)
        print(f"Sender: {smtp_config['email']}", file=sys.stderr)
        print(f"Server: {smtp_config['server']}:{smtp_config['port']}", file=sys.stderr)
        print(f"Recipients: {len(email_data)}", file=sys.stderr)
        
        campaign.status = 'sending'
        db.session.commit()
        
        server = None
        try:
            print("Connecting to SMTP...", file=sys.stderr)
            server = smtplib.SMTP(smtp_config['server'], smtp_config['port'])
            server.starttls()
            
            print("Logging in...", file=sys.stderr)
            server.login(smtp_config['email'], smtp_config['password'])
            print("LOGIN SUCCESSFUL!", file=sys.stderr)
            
            sent = 0
            failed = 0
            
            for index, row in email_data.iterrows():
                name = str(row.get('author', row.get('name', ''))).strip()
                receiver = clean_email(row.get('email', ''))
                
                if not is_valid_email(receiver):
                    failed += 1
                    log = EmailLog(
                        campaign_id=campaign_id,
                        recipient_email=receiver,
                        recipient_name=name,
                        status='failed',
                        error_message='Invalid email format'
                    )
                    db.session.add(log)
                    db.session.commit()
                    print(f"INVALID EMAIL: {receiver}", file=sys.stderr)
                    continue
                
                msg = MIMEMultipart()
                msg["From"] = smtp_config['email']
                msg["To"] = receiver
                msg["Subject"] = campaign.subject
                
                body = campaign.email_body.replace('{name}', name)
                msg.attach(MIMEText(body, "plain"))
                
                try:
                    server.sendmail(smtp_config['email'], receiver, msg.as_string())
                    sent += 1
                    log = EmailLog(
                        campaign_id=campaign_id,
                        recipient_email=receiver,
                        recipient_name=name,
                        status='sent'
                    )
                    db.session.add(log)
                    print(f"SENT to {receiver}", file=sys.stderr)
                except Exception as e:
                    failed += 1
                    log = EmailLog(
                        campaign_id=campaign_id,
                        recipient_email=receiver,
                        recipient_name=name,
                        status='failed',
                        error_message=str(e)
                    )
                    db.session.add(log)
                    print(f"FAILED to {receiver}: {str(e)}", file=sys.stderr)
                
                db.session.commit()
                time.sleep(smtp_config.get('delay', 2))
            
            campaign.sent_count = sent
            campaign.failed_count = failed
            campaign.status = 'completed'
            campaign.completed_at = datetime.utcnow()
            db.session.commit()
            print(f"CAMPAIGN COMPLETE: Sent={sent}, Failed={failed}", file=sys.stderr)
            
        except Exception as e:
            print(f"CRITICAL ERROR: {str(e)}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            campaign.status = 'failed'
            db.session.commit()
            
        finally:
            if server:
                server.quit()
            print(f"=== CAMPAIGN {campaign_id} FINISHED ===", file=sys.stderr)