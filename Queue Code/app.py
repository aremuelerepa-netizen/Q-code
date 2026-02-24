import os
from flask import Flask, request, jsonify, render_template, redirect, url_for
from supabase import create_client, Client

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "qcode_secure_key_777")

# --- 1. CONFIGURATION (Environment Variables) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")

# Master Admin credentials set in Render/Host environment
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 2. FRONTEND ROUTES (Page Rendering) ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status')
def status_page():
    return render_template('status.html')

@app.route('/dashboard')
def admin_dashboard():
    return render_template('Admin page.html')

@app.route('/login')
def login_page():
    return render_template('login page.html')

@app.route('/userpage')
def userpage():
    return render_template('Userpage.html')

@app.route('/register')
def register_page_view():  # Renamed to avoid duplicate function error
    return render_template('org reg page.html')

@app.route('/masteradmin')
def master_admin_view(): # Unique function name
    return render_template('super_admin.html')

# --- 3. THE OFFLINE WEBHOOK (SMS Receiver) ---

@app.route('/webhook/sms', methods=['POST'])
def sms_webhook():
    try:
        # Receives SMS body (Service Code) and Sender Phone
        incoming_msg = request.values.get('Body', '').strip().upper()
        sender_number = request.values.get('From', 'Unknown')

        # Find service by its public code
        service_query = supabase.table('services').select('*').eq('service_code', incoming_msg).execute()
        
        if not service_query.data:
            response_msg = "Error: Invalid Service Code. Please check and try again."
        else:
            service = service_query.data[0]
            
            # Create queue entry for offline user
            new_entry = {
                "service_id": service['id'],
                "visitor_name": f"SMS User ({sender_number[-4:]})",
                "status": "waiting",
                "metadata": {"phone": sender_number},
                "entry_type": "SMS"
            }
            ticket = supabase.table('queue').insert(new_entry).execute()
            
            # Position calculation
            ahead = supabase.table('queue').select('id', count='exact')\
                .eq('service_id', service['id'])\
                .eq('status', 'waiting')\
                .lt('created_at', ticket.data[0]['created_at']).execute()
            
            pos = ahead.count + 1
            response_msg = f"Success! Joined {service['service_name']}. Your position is #{pos}."

        return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Message>{response_msg}</Message></Response>"
    except Exception as e:
        return "Error", 500

# --- 4. AUTH & QUEUE API LOGIC ---

@app.route('/api/auth/login', methods=['POST'])
def combined_login():
    """Checks Master Admin first, then Supabase Auth"""
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')

        # 1. Check Master Admin (Environment Variable)
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            return jsonify({"status": "success", "redirect": "/masteradmin", "role": "master"})

        # 2. Check Standard Supabase Auth
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return jsonify({"status": "success", "redirect": "/dashboard", "session": res.session.access_token})
    except Exception as e:
        return jsonify({"status": "error", "message": "Invalid Credentials"}), 401

@app.route('/api/queue/status/<ticket_id>', methods=['GET'])
def get_status(ticket_id):
    try:
        ticket = supabase.table('queue').select('*, services(service_name)').eq('id', ticket_id).single().execute()
        if not ticket.data: return jsonify({"status": "error"}), 404
        
        ahead = supabase.table('queue').select('id', count='exact')\
            .eq('service_id', ticket.data['service_id'])\
            .eq('status', 'waiting')\
            .lt('created_at', ticket.data['created_at']).execute()

        return jsonify({
            "status": ticket.data['status'],
            "position": 0 if ticket.data['status'] == 'serving' else (ahead.count + 1),
            "service_name": ticket.data['services']['service_name']
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- 5. STARTUP ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
