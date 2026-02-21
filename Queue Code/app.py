import os
from flask import Flask, request, jsonify, render_template
from supabase import create_client, Client

app = Flask(__name__)

# --- SUPABASE CONFIG ---
# These must be set in Render's Environment Variables dashboard
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- FRONTEND ROUTES ---
@app.route('/')
def index():
    # This serves your main landing page
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    # This serves the mobile dashboard for users in queue
    return render_template('dashboard.html')

@app.route('/login')
def login():
    return render_template('login.html')

# --- API: JOIN QUEUE ---
@app.route('/api/queue/join', methods=['POST'])
def join_queue():
    try:
        data = request.json
        # 1. Clean and normalize the input code
        code = data.get('service_code', '').strip().upper()
        visitor = data.get('visitor_name', 'Guest User')

        if not code:
            return jsonify({"status": "error", "message": "Code is required"}), 400

        # 2. Check Supabase 'services' table for the code
        service_query = supabase.table('services').select('*').eq('service_code', code).execute()

        if not service_query.data:
            return jsonify({"status": "error", "message": "Invalid Service Code"}), 404

        service = service_query.data[0]

        # 3. Create the queue entry
        # We include org_id and service_id just like your original code
        new_entry = {
            "service_id": service['id'],
            "org_id": service.get('org_id'),
            "visitor_name": visitor,
            "status": "waiting"
        }
        
        insert_result = supabase.table('queue').insert(new_entry).execute()
        
        if not insert_result.data:
            return jsonify({"status": "error", "message": "Failed to create ticket"}), 500

        ticket = insert_result.data[0]

        # 4. Calculate Position (Count people ahead in line)
        pos_query = supabase.table('queue').select('id', count='exact')\
            .eq('service_id', service['id'])\
            .eq('status', 'waiting')\
            .lt('created_at', ticket['created_at']).execute()

        # Return everything the mobile dashboard needs to function
        return jsonify({
            "status": "success",
            "ticket_id": ticket['id'],
            "service_name": service.get('service_name', 'Service'),
            "position": (pos_query.count or 0) + 1
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- API: LIVE STATUS ---
@app.route('/api/queue/status/<ticket_id>', methods=['GET'])
def get_status(ticket_id):
    try:
        # Fetch ticket and link service name via foreign key join
        ticket = supabase.table('queue').select('*, services(service_name)').eq('id', ticket_id).single().execute()
        
        if not ticket.data:
            return jsonify({"status": "error"}), 404
        
        # Calculate how many people are waiting ahead of this user
        ahead = supabase.table('queue').select('id', count='exact')\
            .eq('service_id', ticket.data['service_id'])\
            .eq('status', 'waiting')\
            .lt('created_at', ticket.data['created_at']).execute()

        # Position is 0 if status changed to 'serving'
        current_pos = 0 if ticket.data['status'] == 'serving' else (ahead.count + 1)

        return jsonify({
            "status": ticket.data['status'],
            "position": current_pos,
            "service_name": ticket.data['services']['service_name']
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- API: COMPLETE SESSION ---
@app.route('/api/queue/complete', methods=['POST'])
def complete_session():
    try:
        data = request.json
        ticket_id = data.get('ticket_id')
        user_code = data.get('end_code', '').strip().upper()

        # Fetch the service end_code to compare
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
    # This block is critical for Render to detect the port
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
