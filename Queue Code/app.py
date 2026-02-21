import os
from flask import Flask, request, jsonify, render_template, redirect
from supabase import create_client, Client

app = Flask(__name__)

# --- SUPABASE CONFIG ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- FRONTEND ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status')
def status_page():
    # Serves the mobile dashboard/ticket status view
    return render_template('status.html')

@app.route('/dashboard')
def admin_dashboard():
    # Keep this if you have a separate admin/business view
    return render_template('Admin page.html')

@app.route('/login')
def login_page():
    return render_template('login page.html')

@app.route('/userpage')
def userpage():
    return render_template('Userpage.html')

# --- API: AUTH & PERSONAL ACCOUNTS ---

@app.route('/api/auth/user-register', methods=['POST'])
def user_register():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        # Supabase Auth for personal accounts
        res = supabase.auth.sign_up({"email": email, "password": password})
        if res.user:
            return jsonify({"status": "success", "message": "Account Created"})
        return jsonify({"status": "error", "message": "Registration failed"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/auth/user-login', methods=['POST'])
def user_login():
    try:
        data = request.json
        res = supabase.auth.sign_in_with_password({
            "email": data.get('email'), 
            "password": data.get('password')
        })
        return jsonify({"status": "success", "session": res.session.access_token})
    except Exception as e:
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401

# --- API: QUEUE OPERATIONS ---

@app.route('/api/auth/join-frictionless', methods=['POST'])
def join_frictionless():
    try:
        data = request.json
        code = data.get('service_code', '').strip().upper()
        name = data.get('name', 'Guest')

        # 1. Find the service
        service_query = supabase.table('services').select('*').eq('service_code', code).execute()
        if not service_query.data:
            return jsonify({"status": "error", "message": "Invalid Service Code"}), 404

        service = service_query.data[0]

        # 2. Create the ticket
        new_ticket = {
            "service_id": service['id'],
            "org_id": service.get('org_id'), # Matches your feature set
            "visitor_name": name,
            "status": "waiting"
        }
        ticket_result = supabase.table('queue').insert(new_ticket).execute()
        
        if not ticket_result.data:
            return jsonify({"status": "error", "message": "Database error"}), 500

        ticket = ticket_result.data[0]

        return jsonify({
            "status": "success", 
            "ticket_id": ticket['id'],
            "organization_name": service.get('service_name', 'Organization')
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/queue/status/<ticket_id>', methods=['GET'])
def get_status(ticket_id):
    try:
        # Fetch ticket and join with service name
        ticket_query = supabase.table('queue').select('*, services(service_name)').eq('id', ticket_id).single().execute()
        
        if not ticket_query.data:
            return jsonify({"status": "error", "message": "Ticket not found"}), 404
        
        ticket = ticket_query.data

        # Calculate position: Count people with 'waiting' status joined before this ticket
        ahead_query = supabase.table('queue').select('id', count='exact')\
            .eq('service_id', ticket['service_id'])\
            .eq('status', 'waiting')\
            .lt('created_at', ticket['created_at']).execute()

        # If admin marks as 'serving', position becomes 0
        current_pos = 0 if ticket['status'] == 'serving' else (ahead_query.count + 1)

        return jsonify({
            "status": ticket['status'],
            "position": current_pos,
            "service_name": ticket['services']['service_name']
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/queue/complete', methods=['POST'])
def complete_session():
    try:
        data = request.json
        ticket_id = data.get('ticket_id')
        user_code = data.get('end_code', '').strip().upper()

        # Get the correct end_code for this service
        ticket = supabase.table('queue').select('service_id').eq('id', ticket_id).single().execute()
        service = supabase.table('services').select('end_code').eq('id', ticket.data['service_id']).single().execute()

        if service.data and service.data['end_code'] == user_code:
            supabase.table('queue').update({"status": "completed"}).eq('id', ticket_id).execute()
            return jsonify({"status": "success"})
        
        return jsonify({"status": "error", "message": "Incorrect End Code"}), 403
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- RENDER BOOT LOGIC ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

