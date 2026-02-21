import os
import random
import string
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "qcode_2026_secure")

# --- 1. INITIALIZE DB ---
db: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

# --- 2. EMAIL OTP FUNCTION ---
def send_otp_email(to_email, otp):
    """Sends OTP using Gmail App Password via Port 465"""
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD") # 16-character code
    
    msg = EmailMessage()
    msg.set_content(f"Your Q-CODE verification code is: {otp}")
    msg["Subject"] = "Verify Your Email"
    msg["From"] = f"Q-CODE <{gmail_user}>"
    msg["To"] = to_email

    try:
        # Port 465 is for SSL; if Render blocks this, we'll use an API instead
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(gmail_user, gmail_pass)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"EMAIL ERROR: {e}")
        return False

# --- 3. ONLINE USER FLOW (EMAIL) ---

@app.route('/api/auth/request-otp', methods=['POST'])
def request_otp():
    email = request.json.get('email')
    otp = str(random.randint(100000, 999999))
    session['temp_otp'], session['temp_email'] = otp, email
    
    if send_otp_email(email, otp):
        return jsonify({"status": "sent"})
    return jsonify({"status": "error", "message": "Email blocked by server. Check Render settings."}), 500

@app.route('/api/auth/verify-otp', methods=['POST'])
def verify_otp():
    user_otp = request.json.get('otp')
    if user_otp == session.get('temp_otp'):
        # On success, generate the permanent login code
        login_code = 'QC-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        db.table("queue").upsert({"email": session['temp_email'], "login_code": login_code}, on_conflict="email").execute()
        return jsonify({"status": "success", "login_code": login_code})
    return jsonify({"status": "invalid"}), 401

# --- 4. OFFLINE USER FLOW (SMS WEBHOOK) ---

@app.route('/api/sms/incoming', methods=['POST'])
def incoming_sms():
    """Triggered when an offline user texts a service code to your phone number"""
    data = request.json
    sender_phone = data.get('from') # The user's phone number
    service_code = data.get('message', '').strip().upper() # e.g. "ZENITH01"

    # Check if the code belongs to a valid registered company
    res = db.table("organizations").select("name", "id").eq("id", service_code).execute()
    
    if res.data:
        org = res.data[0]
        # Add them to the queue automatically
        db.table("queue").insert({
            "phone": sender_phone, 
            "org_id": org['id'], 
            "entry_type": "SMS_OFFLINE"
        }).execute()
        reply = f"Q-CODE: You are now in line for {org['name']}. We will text you when it's your turn."
    else:
        reply = "Q-CODE: Invalid Service Code. Please check the code and try again."

    # Return the reply to the SMS Gateway app to send back to the user
    return jsonify({"to": sender_phone, "message": reply})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
