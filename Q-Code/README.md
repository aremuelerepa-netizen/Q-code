# Q-Code Simplified Backend

A simple, single-file Flask backend for queue management system with SMS, WhatsApp, and AI integration.

## Quick Start

### 1. Setup
```bash
# Create .env file
cp .env.example .env
# Edit .env with your API keys

# Install dependencies
pip install -r requirements.txt

# Run app
python app.py
```

### 2. Open Frontend
- User: `http://localhost:5000/index/index.html`
- Admin: `http://localhost:5000/index/admin-login.html`

## API Endpoints

### User Routes
- `POST /api/register` - Register user with phone
- `POST /api/verify-otp` - Verify OTP code
- `POST /api/join` - Join a queue
- `GET /api/my-queues` - Get user's active queues
- `GET /api/position/<id>` - Get queue position
- `POST /api/leave/<id>` - Leave queue
- `GET /api/services` - Get available services

### Admin Routes
- `POST /api/admin-register` - Register organization
- `POST /api/admin-login` - Admin login
- `GET /api/admin-dashboard` - Dashboard stats
- `POST /api/next-queue/<id>` - Call next person
- `POST /api/complete-service/<id>` - Complete service
- `POST /api/create-service` - Create new service

### Webhooks
- `POST /api/sms-webhook` - Handle incoming SMS
- `POST /api/stats` - System statistics

## Features

✅ User registration with OTP verification via SMS
✅ Queue management (join, leave, track position)
✅ Real-time wait time predictions using Groq AI
✅ SMS and WhatsApp notifications
✅ Admin dashboard for queue control
✅ Background jobs (queue status check, no-show detection)
✅ JWT authentication
✅ SQLite/PostgreSQL support
✅ Production-ready (Render deployment)

## Environment Variables

See `.env.example` for all configuration options:
- Database URL
- JWT secret
- SMS provider credentials (Twilio/Africa's Talking)
- WhatsApp API credentials
- Groq API key

## Deployment

### Render
1. Push code to GitHub
2. Connect repository in Render dashboard
3. Set environment variables in Render settings
4. Deploy - Procfile will handle the rest

### Local Development
```bash
python app.py
# App runs on http://localhost:5000
```

## Database Models

- **User**: Phone auth, OTP verification
- **Organization**: Company/admin management
- **Service**: Queue types with service codes
- **QueueEntry**: Individual queue positions with wait time predictions
- **Notification**: SMS/WhatsApp/email tracking

## Notes

- This is a simplified, single-file version
- All logic combined in one `app.py` for easy understanding
- HTML files in `index/` folder for frontend
- Background jobs run every 2-10 minutes for queue management
