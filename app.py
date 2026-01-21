# -*- coding: utf-8 -*-
import sys
import io
# Set UTF-8 encoding for stdout/stderr on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for
from datetime import datetime
import os
import socket
import requests
from urllib.parse import urlparse
import hashlib
import json
from functools import wraps
import qrcode
from PIL import Image, ImageDraw, ImageFont
import base64
from io import BytesIO
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production-' + str(hash('whatsthat')))
# Make sessions permanent so users stay logged in
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///whatsthat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Database models
class Venue(db.Model):
    """Venue model"""
    __tablename__ = 'venues'
    id = db.Column(db.String(8), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    owner_email = db.Column(db.String(255), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    logo_path = db.Column(db.String(255), nullable=True)
    qr_background = db.Column(db.String(255), nullable=True)
    allowed_genres = db.Column(JSON, nullable=True)
    
    def to_dict(self):
        return {
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'logo_path': self.logo_path,
            'qr_background': self.qr_background,
            'allowed_genres': self.allowed_genres or [],
            'owner_email': self.owner_email
        }

class VenueQueue(db.Model):
    """Venue queue item model"""
    __tablename__ = 'venue_queues'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    venue_id = db.Column(db.String(8), db.ForeignKey('venues.id', ondelete='CASCADE'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255), nullable=True)
    task_id = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    
    def to_dict(self):
        return {
            'filename': self.filename,
            'title': self.title,
            'task_id': self.task_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }

class VenueTable(db.Model):
    """Venue table model"""
    __tablename__ = 'venue_tables'
    id = db.Column(db.String(8), primary_key=True)
    venue_id = db.Column(db.String(8), db.ForeignKey('venues.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    submit_url = db.Column(db.String(500), nullable=False)
    qr_code = db.Column(db.String(500), nullable=True)
    
    def to_dict(self):
        return {
            'name': self.name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'submit_url': self.submit_url,
            'qr_code': self.qr_code
        }

class TableRequest(db.Model):
    """Table request model"""
    __tablename__ = 'table_requests'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    table_id = db.Column(db.String(8), db.ForeignKey('venue_tables.id', ondelete='CASCADE'), nullable=False, index=True)
    task_id = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String(50), default='pending', nullable=False)
    
    def to_dict(self):
        return {
            'task_id': self.task_id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'status': self.status
        }

class TaskMapping(db.Model):
    """Task to venue mapping"""
    __tablename__ = 'task_mappings'
    task_id = db.Column(db.String(255), primary_key=True)
    venue_id = db.Column(db.String(8), db.ForeignKey('venues.id', ondelete='CASCADE'), nullable=False, index=True)

class SongTitle(db.Model):
    """Song title mapping"""
    __tablename__ = 'song_titles'
    task_id = db.Column(db.String(255), primary_key=True)
    title = db.Column(db.String(255), nullable=False)

@app.before_request
def make_session_permanent():
    """Make sessions permanent if user chose to stay logged in"""
    # Only make permanent if user is logged in and chose to remember
    # Default to True if not set (for backward compatibility)
    if session.get('user_id'):
        remember_me = session.get('remember_me', True)
        session.permanent = remember_me

# Create directories if they don't exist
BASE_DIR = os.path.dirname(__file__)

# Use persistent volume if available (Railway Volumes), otherwise use local directory
PERSISTENT_DATA_DIR = os.environ.get('PERSISTENT_DATA_DIR', None)
if PERSISTENT_DATA_DIR and os.path.exists(PERSISTENT_DATA_DIR):
    # Use Railway volume for persistent storage
    DATA_BASE_DIR = PERSISTENT_DATA_DIR
    print(f"✅ Using persistent volume at: {DATA_BASE_DIR}")
    # Also keep BASE_DIR for static files that should stay in the app directory
    # Images and uploaded files go to DATA_BASE_DIR, but we can migrate old images
    OLD_BASE_DIR = BASE_DIR  # Keep reference to old location for migration
else:
    # Fall back to local directory
    DATA_BASE_DIR = BASE_DIR
    OLD_BASE_DIR = BASE_DIR
    print(f"📁 Using local directory: {DATA_BASE_DIR}")

MESSAGES_DIR = os.path.join(DATA_BASE_DIR, "messages")
AUDIO_DIR = os.path.join(DATA_BASE_DIR, "audio")
# Static images from Git repo stay in BASE_DIR/img (not in volume)
IMG_DIR = os.path.join(BASE_DIR, "img")
VENUE_LOGOS_DIR = os.path.join(DATA_BASE_DIR, "venue_logos")
VENUE_QR_CODES_DIR = os.path.join(DATA_BASE_DIR, "venue_qr_codes")
os.makedirs(MESSAGES_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(VENUE_LOGOS_DIR, exist_ok=True)
os.makedirs(VENUE_QR_CODES_DIR, exist_ok=True)

# Suno configuration
SUNO_API_BASE = "https://api.sunoapi.org"
# Use environment variable for API key (more secure)
SUNO_API_KEY = os.environ.get("SUNO_API_KEY", "71eeeb5e47a6c71175731530f6b2635a")
# Google Places API (optional, used for demo venue profiling)
GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY")

# Get base URL from current request
def get_base_url():
    """Get the base URL from the current request"""
    from flask import has_request_context
    if has_request_context():
        return request.url_root.rstrip('/')
    return None

# Detect if running locally (for callback URL)
def get_callback_base_url():
    """Get the base URL for callbacks - use request URL if available, otherwise skip callback for local"""
    base_url = get_base_url()
    if base_url and base_url.startswith("http"):
        return base_url
    # If running locally, return None to skip callback (will use polling instead)
    return None

# In-memory store for task_id -> audio_file mapping (from callbacks)
task_audio_map = {}
# Store song titles: task_id -> title
song_titles = {}
# Track which venue each task belongs to: task_id -> venue_id
task_to_venue = {}
# Venue queue system: venue_id -> list of songs (each song has: filename, title, task_id, timestamp)
venue_queues = {}
# Venue metadata: venue_id -> {name, created_at, logo_path, owner_email}
venue_metadata = {}
# Venue ownership: user_email -> [venue_id, venue_id, ...]
venue_owners = {}
# Venue tables: venue_id -> {table_id: {name, created_at, qr_code, submit_url}}
venue_tables = {}
# OpenAI API key for DALL-E image generation
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# Table song requests: table_id -> list of {task_id, timestamp, status}
table_requests = {}

# Data persistence files - MUST use DATA_BASE_DIR (persistent volume) not BASE_DIR!
DATA_DIR = os.path.join(DATA_BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
print(f"📁 DATA_DIR set to: {DATA_DIR} (using {'persistent volume' if PERSISTENT_DATA_DIR and os.path.exists(PERSISTENT_DATA_DIR) else 'local directory'})")
VENUE_METADATA_FILE = os.path.join(DATA_DIR, "venue_metadata.json")
VENUE_QUEUES_FILE = os.path.join(DATA_DIR, "venue_queues.json")
TASK_TO_VENUE_FILE = os.path.join(DATA_DIR, "task_to_venue.json")
SONG_TITLES_FILE = os.path.join(DATA_DIR, "song_titles.json")
VENUE_OWNERS_FILE = os.path.join(DATA_DIR, "venue_owners.json")
VENUE_TABLES_FILE = os.path.join(DATA_DIR, "venue_tables.json")
TABLE_REQUESTS_FILE = os.path.join(DATA_DIR, "table_requests.json")

def load_data():
    """Load all data from JSON files"""
    global venue_metadata, venue_queues, task_to_venue, song_titles, venue_owners, venue_tables, table_requests
    
    print(f"📂 Loading data from {DATA_DIR}...")
    print(f"   DATA_DIR exists: {os.path.exists(DATA_DIR)}")
    print(f"   VENUE_METADATA_FILE: {VENUE_METADATA_FILE}")
    print(f"   VENUE_OWNERS_FILE: {VENUE_OWNERS_FILE}")
    
    # Load venue metadata
    if os.path.exists(VENUE_METADATA_FILE):
        try:
            file_size = os.path.getsize(VENUE_METADATA_FILE)
            print(f"   📄 venue_metadata.json exists ({file_size} bytes)")
            with open(VENUE_METADATA_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    venue_metadata.clear()  # Clear first to avoid stale data
                    venue_metadata.update(loaded)
                    print(f"   ✅ Loaded {len(venue_metadata)} venues from venue_metadata.json")
                    print(f"   Venue IDs: {list(venue_metadata.keys())}")
                    for vid, vdata in venue_metadata.items():
                        print(f"      {vid}: {vdata.get('name', 'Unnamed')} (owner: {vdata.get('owner_email', 'None')})")
                else:
                    print(f"   ⚠️ venue_metadata.json is not a dict, ignoring")
        except Exception as e:
            print(f"   ❌ Error loading venue_metadata: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"   ⚠️ venue_metadata.json does not exist yet at {VENUE_METADATA_FILE}")
    
    # Load venue queues
    if os.path.exists(VENUE_QUEUES_FILE):
        try:
            with open(VENUE_QUEUES_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    venue_queues.update(loaded)
        except Exception as e:
            print(f"Error loading venue_queues: {e}")
            import traceback
            traceback.print_exc()
    
    # Load task to venue mapping
    if os.path.exists(TASK_TO_VENUE_FILE):
        try:
            with open(TASK_TO_VENUE_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    task_to_venue.update(loaded)
        except Exception as e:
            print(f"Error loading task_to_venue: {e}")
            import traceback
            traceback.print_exc()
    
    # Load song titles
    if os.path.exists(SONG_TITLES_FILE):
        try:
            with open(SONG_TITLES_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    song_titles.update(loaded)
        except Exception as e:
            print(f"Error loading song_titles: {e}")
            import traceback
            traceback.print_exc()
    
    # Load venue owners
    if os.path.exists(VENUE_OWNERS_FILE):
        try:
            file_size = os.path.getsize(VENUE_OWNERS_FILE)
            print(f"   📄 venue_owners.json exists ({file_size} bytes)")
            with open(VENUE_OWNERS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    venue_owners.clear()  # Clear first to avoid stale data
                    venue_owners.update(loaded)
                    print(f"   ✅ Loaded {len(venue_owners)} venue owners from venue_owners.json")
                    print(f"   Owner emails: {list(venue_owners.keys())}")
                    for email, venues in venue_owners.items():
                        print(f"      {email}: {venues}")
                else:
                    print(f"   ⚠️ venue_owners.json is not a dict, ignoring")
        except Exception as e:
            print(f"   ❌ Error loading venue_owners: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"   ⚠️ venue_owners.json does not exist yet at {VENUE_OWNERS_FILE}")
    
    # Load venue tables
    if os.path.exists(VENUE_TABLES_FILE):
        try:
            with open(VENUE_TABLES_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    venue_tables.update(loaded)
        except Exception as e:
            print(f"Error loading venue_tables: {e}")
            import traceback
            traceback.print_exc()
    
    # Load table requests
    if os.path.exists(TABLE_REQUESTS_FILE):
        try:
            with open(TABLE_REQUESTS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    table_requests.update(loaded)
        except Exception as e:
            print(f"Error loading table_requests: {e}")
            import traceback
            traceback.print_exc()

def save_data():
    """Save all data to JSON files"""
    try:
        # Ensure data directory exists
        os.makedirs(DATA_DIR, exist_ok=True)
        
        print(f"💾 Saving data to {DATA_DIR}...")
        print(f"   venue_metadata keys: {list(venue_metadata.keys())}")
        print(f"   venue_owners keys: {list(venue_owners.keys())}")
        
        # Save venue metadata
        with open(VENUE_METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(venue_metadata, f, indent=2, default=str)
            f.flush()  # Force write to disk
            os.fsync(f.fileno())  # Ensure OS writes to disk
        print(f"   ✅ Saved venue_metadata ({len(venue_metadata)} venues) to {VENUE_METADATA_FILE}")
        
        # Save venue queues
        with open(VENUE_QUEUES_FILE, 'w', encoding='utf-8') as f:
            json.dump(venue_queues, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        print(f"   ✅ Saved venue_queues ({len(venue_queues)} queues)")
        
        # Save task to venue mapping
        with open(TASK_TO_VENUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(task_to_venue, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        
        # Save song titles
        with open(SONG_TITLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(song_titles, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        
        # Save venue owners
        with open(VENUE_OWNERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(venue_owners, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        print(f"   ✅ Saved venue_owners ({len(venue_owners)} owners) to {VENUE_OWNERS_FILE}")
        
        # Save venue tables
        with open(VENUE_TABLES_FILE, 'w', encoding='utf-8') as f:
            json.dump(venue_tables, f, indent=2, default=str)
        
        # Save table requests
        with open(TABLE_REQUESTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(table_requests, f, indent=2, default=str)
        
        # Verify files were created
        if os.path.exists(VENUE_METADATA_FILE):
            file_size = os.path.getsize(VENUE_METADATA_FILE)
            print(f"   ✅ Verified: venue_metadata.json exists ({file_size} bytes)")
        else:
            print(f"   ❌ ERROR: venue_metadata.json was not created!")
        
        print(f"✅ All data saved successfully")
    except Exception as e:
        print(f"❌ ERROR saving data: {e}")
        import traceback
        traceback.print_exc()

# Ensure img directory exists (for static images from Git repo)
if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR, exist_ok=True)
    print(f"📁 Created img directory: {IMG_DIR}")
    
    # Migrate venue_logos directory
    if os.path.exists(old_logos_dir) and not os.path.exists(VENUE_LOGOS_DIR):
        try:
            shutil.copytree(old_logos_dir, VENUE_LOGOS_DIR)
            print(f"✅ Migrated venue logos from {old_logos_dir} to {VENUE_LOGOS_DIR}")
        except Exception as e:
            print(f"⚠️ Could not migrate venue logos: {e}")
    
    # Migrate venue_qr_codes directory
    if os.path.exists(old_qr_dir) and not os.path.exists(VENUE_QR_CODES_DIR):
        try:
            shutil.copytree(old_qr_dir, VENUE_QR_CODES_DIR)
            print(f"✅ Migrated QR codes from {old_qr_dir} to {VENUE_QR_CODES_DIR}")
        except Exception as e:
            print(f"⚠️ Could not migrate QR codes: {e}")

# Load data on startup
print("🚀 Starting application - loading data...")
load_data()
print("✅ Application startup complete")

# User authentication storage - MUST use DATA_BASE_DIR for persistence!
USERS_FILE = os.path.join(DATA_BASE_DIR, "users.json")

# Hardwired admin credentials
ADMIN_EMAIL = "admin@whatsthat.com"
ADMIN_PASSWORD = "admin123"  # Change this in production!

def load_users():
    """Load users from file, with migration from old location"""
    users = {}
    
    # First, try to load from the persistent location
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                users = json.load(f)
            print(f"✅ Loaded {len(users)} user(s) from {USERS_FILE}")
        except Exception as e:
            print(f"❌ Error loading users from {USERS_FILE}: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"📄 Users file does not exist: {USERS_FILE}")
        
        # Try to migrate from old location (BASE_DIR)
        old_users_file = os.path.join(BASE_DIR, "users.json")
        if os.path.exists(old_users_file) and BASE_DIR != DATA_BASE_DIR:
            try:
                print(f"🔄 Migrating users.json from {old_users_file} to {USERS_FILE}")
                with open(old_users_file, 'r', encoding='utf-8') as f:
                    users = json.load(f)
                # Save to new location
                save_users(users)
                print(f"✅ Migrated {len(users)} user(s) to persistent location")
            except Exception as e:
                print(f"⚠️ Could not migrate users.json: {e}")
                import traceback
                traceback.print_exc()
    
    # Always add hardwired admin account
    admin_existing = users.get(ADMIN_EMAIL, {})
    users[ADMIN_EMAIL] = {
        'email': ADMIN_EMAIL,
        'name': admin_existing.get('name') or 'Admin',
        'password_hash': admin_existing.get('password_hash') or hash_password(ADMIN_PASSWORD),
        'created_at': admin_existing.get('created_at') or datetime.now().isoformat(),
        'is_admin': True,
        # Admins skip the end-user onboarding wizard
        'onboarding_completed': True
    }
    
    return users

def save_users(users):
    """Save users to file (preserves hardwired admin)"""
    # Remove admin from saved users (it's always hardwired)
    users_to_save = {k: v for k, v in users.items() if k != ADMIN_EMAIL}
    try:
        # Ensure directory exists
        users_dir = os.path.dirname(USERS_FILE)
        if users_dir:  # Only create if there's a directory path
            os.makedirs(users_dir, exist_ok=True)
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_to_save, f, indent=2, ensure_ascii=False)
            f.flush()  # Force write to disk
            os.fsync(f.fileno())  # Ensure OS writes to disk
        print(f"✅ Saved {len(users_to_save)} user(s) to {USERS_FILE}")
        print(f"   File exists after save: {os.path.exists(USERS_FILE)}")
        if os.path.exists(USERS_FILE):
            file_size = os.path.getsize(USERS_FILE)
            print(f"   File size: {file_size} bytes")
    except Exception as e:
        print(f"❌ Error saving users to {USERS_FILE}: {e}")
        import traceback
        traceback.print_exc()

def hash_password(password):
    """Hash a password"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    """Verify a password against its hash"""
    return hash_password(password) == hashed

# Load users on startup
users = load_users()

def require_login(f):
    """Decorator to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def landing():
    """Landing page for bars/restaurants"""
    base_url = get_base_url() or ''
    return render_template('landing.html', base_url=base_url)


@app.route('/chat')
def chat():
    """Chat interface for testing"""
    return render_template('index.html')


@app.route('/venue/<venue_id>/submit')
def venue_submit(venue_id):
    """Submission page for users to request songs for a specific venue"""
    # Get allowed genres and custom instructions for this venue
    venue_data = venue_metadata.get(venue_id, {})
    allowed_genres = venue_data.get('allowed_genres', ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical'])
    custom_instructions = venue_data.get('custom_instructions', None)
    return render_template('venue_submit.html', venue_id=venue_id, table_id=None, allowed_genres=allowed_genres, custom_instructions=custom_instructions)


@app.route('/venue/<venue_id>/stream')
def venue_stream(venue_id):
    """Streaming/queue page for venues to play songs"""
    return render_template('venue_stream.html', venue_id=venue_id)


@app.route('/venue/<venue_id>/queue-view')
def venue_queue_view(venue_id):
    """Public queue-only view for displaying on TVs/devices"""
    load_data()
    
    # Get venue name from metadata
    venue_name = venue_metadata.get(venue_id, {}).get('name', f'Venue {venue_id}')
    
    return render_template('venue_queue_view.html', venue_id=venue_id, venue_name=venue_name)


@app.route('/demo/generate', methods=['POST'])
def generate_demo():
    """Generate a demo venue for the landing page"""
    try:
        data = request.get_json()
        venue_name = data.get('venue_name', '').strip()
        business_email = data.get('business_email', '').strip()
        venue_type = data.get('venue_type', '').strip()
        city = data.get('city', '').strip()
        
        if not venue_name or not business_email or not city:
            return jsonify({'success': False, 'error': 'Venue name, city, and business email are required'}), 400
        
        # Generate a demo venue ID
        demo_id = hashlib.md5(f"demo_{venue_name}_{business_email}".encode()).hexdigest()[:8]
        
        # Create demo venue metadata
        load_data()
        venue_metadata[demo_id] = {
            'name': venue_name,
            'owner_email': business_email,
            'created_at': datetime.now().isoformat(),
            'is_demo': True,
            'venue_type': venue_type,
            'city': city,
            'demo_created_at': datetime.now().isoformat()
        }
        
        # Initialize empty queue for demo
        venue_queues[demo_id] = []
        venue_owners[business_email] = venue_owners.get(business_email, []) + [demo_id]
        
        # Save data
        save_data()
        
        # Generate QR code for demo
        base_url = get_base_url() or request.host_url.rstrip('/')
        submit_url = f"{base_url}/venue/{demo_id}/submit"
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(submit_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert QR to base64
        buffered = BytesIO()
        qr_img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode()
        
        return jsonify({
            'success': True,
            'demo_id': demo_id,
            'venue_name': venue_name,
            'qr_code': f"data:image/png;base64,{qr_base64}",
            'submit_url': submit_url,
            'stream_url': f"{base_url}/venue/{demo_id}/stream"
        })
    except Exception as e:
        import traceback
        print(f"❌ Error generating demo: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/demo/<demo_id>/submit', methods=['POST'])
def demo_submit_song(demo_id):
    """Submit a song request for a demo venue"""
    try:
        data = request.get_json()
        message = data.get('message', '').strip()
        table_id = data.get('table_id', 'demo-table-1')
        
        if not message:
            return jsonify({'success': False, 'error': 'Message is required'}), 400
        
        # Save message to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"message_{timestamp}.txt"
        filepath = os.path.join(MESSAGES_DIR, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(message)
        print(f"✅ Saved message to: {filepath}")
        
        # Trigger Suno music generation
        print("🎵 Calling Suno API for demo...")
        music_info = call_suno_generate_music(prompt=message, venue_id=demo_id, table_id=table_id, genre=None)
        print(f"🎵 Suno API response: {music_info}")
        
        # Return success with timestamp + music generation info
        display_timestamp = datetime.now().strftime("%H:%M:%S")
        response_data = {
            'success': True,
            'timestamp': display_timestamp,
            'message': message,
            'music_generation': music_info,
            'venue_id': demo_id
        }
        print(f"✅ Returning success response: {response_data}")
        return jsonify(response_data)
    except Exception as e:
        import traceback
        print(f"❌ Error in demo submit: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/demo/<demo_id>/queue')
def demo_get_queue(demo_id):
    """Get the queue for a demo venue"""
    try:
        load_data()
        check_and_process_pending_tasks(demo_id)
        queue = venue_queues.get(demo_id, [])
        return jsonify({
            'venue_id': demo_id,
            'queue': queue,
            'queue_length': len(queue)
        })
    except Exception as e:
        import traceback
        print(f"❌ Error getting demo queue: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


def fetch_venue_profile_from_google(name: str, city: str):
    """
    Use Google Places Text Search + Details to build a small venue profile.
    Only used for the landing-page demo; fails soft if API key is missing.
    """
    if not GOOGLE_PLACES_API_KEY:
        print("⚠️ GOOGLE_PLACES_API_KEY not set, skipping venue profile lookup")
        return None

    try:
        query = f"{name}, {city}".strip()
        text_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {"query": query, "key": GOOGLE_PLACES_API_KEY}
        resp = requests.get(text_url, params=params, timeout=8)
        if resp.status_code != 200:
            print(f"⚠️ Google Text Search HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        data = resp.json()
        results = data.get("results") or []
        if not results:
            print("⚠️ Google Text Search returned no results")
            return None
        first = results[0]
        place_id = first.get("place_id")
        if not place_id:
            return None

        details_url = "https://maps.googleapis.com/maps/api/place/details/json"
        d_params = {
            "place_id": place_id,
            "key": GOOGLE_PLACES_API_KEY,
            "fields": "name,formatted_address,website,types,rating,user_ratings_total,reviews,editorial_summary"
        }
        d_resp = requests.get(details_url, params=d_params, timeout=8)
        if d_resp.status_code != 200:
            print(f"⚠️ Google Details HTTP {d_resp.status_code}: {d_resp.text[:200]}")
            return None
        d_data = d_resp.json()
        result = d_data.get("result") or {}

        profile = {
            "name": result.get("name") or name,
            "formatted_address": result.get("formatted_address") or city,
            "website": result.get("website"),
            "types": result.get("types", []),
            "rating": result.get("rating"),
            "user_ratings_total": result.get("user_ratings_total"),
            "editorial_summary": (result.get("editorial_summary") or {}).get("overview"),
            "reviews": [],
            "review_highlights": []
        }
        for r in (result.get("reviews") or [])[:5]:
            text = r.get("text") or ""
            snippet = text.strip()
            if len(snippet) > 220:
                snippet = snippet[:217].rsplit(" ", 1)[0] + "..."
            review_obj = {
                "author_name": r.get("author_name"),
                "rating": r.get("rating"),
                "text": text,
                "snippet": snippet,
            }
            profile["reviews"].append(review_obj)
            profile["review_highlights"].append(snippet)

        # Optional: scrape basic text from the venue website to give GPT more flavor (menu, vibe, etc.)
        website = profile.get("website")
        if website:
            try:
                w_resp = requests.get(website, timeout=8)
                if w_resp.status_code == 200 and "text" in w_resp.headers.get("Content-Type", ""):
                    html = w_resp.text
                    # Very lightweight HTML to text: strip tags and collapse whitespace
                    import re
                    text = re.sub(r"<script[\\s\\S]*?</script>", " ", html, flags=re.IGNORECASE)
                    text = re.sub(r"<style[\\s\\S]*?</style>", " ", text, flags=re.IGNORECASE)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\\s+", " ", text)
                    text = text.strip()
                    if text:
                        profile["website_text"] = text[:1200]
            except Exception as e:
                print(f"⚠️ Error scraping venue website {website}: {e}")

        return profile
    except Exception as e:
        print(f"⚠️ Error fetching venue profile from Google: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_demo_prompt_with_gpt(profile: dict, fallback_name: str):
    """
    Use GPT to write a fun Suno prompt for the landing-page demo, based on venue profile.
    """
    if not OPENAI_API_KEY:
        print("⚠️ OPENAI_API_KEY not set, cannot generate demo prompt")
        return None
    try:
        venue_name = profile.get("name") or fallback_name
        prompt_instructions = (
            "You are writing a short creative prompt for an AI music generator (Suno) for a bar/venue demo.\n"
            "Use the venue profile to make the prompt feel SPECIFIC:\n"
            "- Mention the city or neighborhood.\n"
            "- Mention the type of place (e.g. dive bar, rooftop cocktail bar, sports bar, live music venue).\n"
            "- If you see food or drink items on the website text or in reviews (wings, tacos, margaritas, karaoke, etc.), weave ONE of them into the prompt.\n"
            "- Optionally nod to something guests love from the reviews (friendly staff, great crowd, karaoke nights, etc.).\n"
            "Write ONE energetic sentence that describes a fun song about this particular venue, its vibe, and its guests.\n"
            "Do NOT mention Suno, AI, or that this is a demo. Just a natural song idea.\n"
            "Maximum 180 characters.\n\n"
            f"Venue profile JSON:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
            "Return ONLY the prompt text, no quotes, no extra explanation."
        )
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "You write short, punchy song prompts for an AI music generator."},
                {"role": "user", "content": prompt_instructions}
            ],
            "temperature": 0.7,
            "max_tokens": 80
        }
        resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"⚠️ GPT prompt API HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        suggestion = content.strip().strip('"').strip("'")
        if not suggestion:
            return None
        # Ensure the venue name is explicitly mentioned in the prompt
        if venue_name and venue_name.lower() not in suggestion.lower():
            suggestion = f"{venue_name} – {suggestion}"
        if len(suggestion) > 180:
            suggestion = suggestion[:177].rsplit(" ", 1)[0] + "..."
        return suggestion
    except Exception as e:
        print(f"⚠️ Error generating demo prompt with GPT: {e}")
        import traceback
        traceback.print_exc()
        return None


@app.route('/demo/<demo_id>/suggest-prompt', methods=['POST'])
def demo_suggest_prompt(demo_id):
    """
    Landing-page helper: build a venue profile and suggest a Suno prompt.
    """
    try:
        data = request.get_json() or {}
        load_data()
        meta = venue_metadata.get(demo_id, {})
        venue_name = data.get("venue_name") or meta.get("name", f"Venue {demo_id}")
        city = data.get("city") or meta.get("city", "")

        profile = fetch_venue_profile_from_google(venue_name, city) if (venue_name and city) else None
        suggestion = generate_demo_prompt_with_gpt(profile or {"name": venue_name, "city": city}, venue_name)

        return jsonify({
            "success": True,
            "prompt": suggestion or "",
            "profile": profile
        })
    except Exception as e:
        import traceback
        print(f"❌ Error in demo_suggest_prompt: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/venue/create', methods=['POST'])
@require_login
def create_venue():
    """Create a new venue and return its ID and QR codes"""
    import uuid
    venue_id = str(uuid.uuid4())[:8]  # Short unique ID
    # Default allowed genres: all available genres
    all_genres = ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical']
    # Get the logged-in user
    user_email = session.get('user_id')
    
    venue_metadata[venue_id] = {
        'name': request.json.get('name', f'Venue {venue_id}'),
        'created_at': datetime.now().isoformat(),
        'logo_path': None,
        'qr_background': None,
        'allowed_genres': all_genres,  # Default to all genres
        'owner_email': user_email  # Associate venue with user
    }
    venue_queues[venue_id] = []  # Initialize empty queue
    
    # Track venue ownership
    if user_email:
        if user_email not in venue_owners:
            venue_owners[user_email] = []
        venue_owners[user_email].append(venue_id)
    
    # Save data to disk
    save_data()
    
    base_url = get_base_url()
    submit_url = f"{base_url}/venue/{venue_id}/submit"
    stream_url = f"{base_url}/venue/{venue_id}/stream"
    
    # Create tables if num_tables is provided
    num_tables = request.json.get('num_tables', 0)
    tables = []
    if num_tables and num_tables > 0:
        if venue_id not in venue_tables:
            venue_tables[venue_id] = {}
        
        for i in range(int(num_tables)):
            table_id = str(uuid.uuid4())[:8]
            table_name = f'Table {i + 1}'
            table_submit_url = f"{base_url}/venue/{venue_id}/table/{table_id}/submit"
            
            venue_tables[venue_id][table_id] = {
                'name': table_name,
                'created_at': datetime.now().isoformat(),
                'submit_url': table_submit_url,
                'qr_code': f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={table_submit_url}"
            }
            
            # Initialize empty request list for this table
            table_requests[table_id] = []
            save_data()  # Save new table
            
            tables.append({
                'table_id': table_id,
                'name': table_name,
                'submit_url': table_submit_url,
                'qr_code': venue_tables[venue_id][table_id]['qr_code']
            })
    
    response_data = {
        'venue_id': venue_id,
        'submit_url': submit_url,
        'stream_url': stream_url,
        'submit_qr': f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={submit_url}",
        'stream_qr': f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={stream_url}",
        'tables': tables
    }
    
    return jsonify(response_data)


@app.route('/venue/<venue_id>/info')
@require_login
def get_venue_info(venue_id):
    """Get venue information including metadata"""
    user_email = session.get('user_id')
    is_admin = session.get('is_admin', False)
    
    # Check if user owns this venue or is admin
    if not is_admin:
        user_venues = venue_owners.get(user_email, [])
        if venue_id not in user_venues:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
    
    if venue_id not in venue_metadata:
        return jsonify({'success': False, 'error': 'Venue not found'}), 404
    
    metadata = venue_metadata[venue_id]
    queue = venue_queues.get(venue_id, [])
    tables = venue_tables.get(venue_id, {})
    
    # Get table list
    tables_list = []
    for table_id, table_data in tables.items():
        tables_list.append({
            'table_id': table_id,
            'name': table_data['name'],
            'created_at': table_data['created_at'],
            'submit_url': table_data['submit_url'],
            'qr_code': table_data['qr_code']
        })
    
    base_url = get_base_url() or ''
    return jsonify({
        'success': True,
        'venue_id': venue_id,
        'name': metadata.get('name', f'Venue {venue_id}'),
        'created_at': metadata.get('created_at'),
        'queue_length': len(queue),
        'tables': tables_list,
        'submit_url': f"{base_url}/venue/{venue_id}/submit",
        'stream_url': f"{base_url}/venue/{venue_id}/stream",
        'submit_qr': f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={base_url}/venue/{venue_id}/submit",
        'stream_qr': f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={base_url}/venue/{venue_id}/stream"
    })


@app.route('/venue/<venue_id>/queue')
def get_venue_queue(venue_id):
    """Get the current queue for a venue"""
    # Poll for completed songs before returning queue
    check_and_process_pending_tasks(venue_id)
    queue = venue_queues.get(venue_id, [])
    return jsonify({
        'venue_id': venue_id,
        'queue': queue,
        'queue_length': len(queue)
    })


def check_and_process_pending_tasks(venue_id=None):
    """Poll Suno API for pending tasks and download/completed songs"""
    try:
        # Get all pending tasks (tasks in task_to_venue that haven't been processed)
        pending_tasks = {}
        if venue_id:
            # Check only tasks for this venue
            pending_tasks = {task_id: v_id for task_id, v_id in task_to_venue.items() if v_id == venue_id}
        else:
            # Check all pending tasks
            pending_tasks = dict(task_to_venue)
        
        if not pending_tasks:
            return
        
        print(f"🔍 Polling {len(pending_tasks)} pending task(s)...")
        
        for task_id, v_id in list(pending_tasks.items()):
            try:
                print(f"🔍 Polling task {task_id} for venue {v_id}...")
                # Use the same endpoint as get_suno_music_status
                url = f"{SUNO_API_BASE}/api/v1/generate/record-info"
                headers = {
                    "Authorization": f"Bearer {SUNO_API_KEY}",
                    "Content-Type": "application/json",
                }
                params = {"taskId": task_id}
                
                status_response = requests.get(url, headers=headers, params=params, timeout=20)
                
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    print(f"   Status response for {task_id}: code={status_data.get('code')}")
                    
                    if status_data.get("code") == 200:
                        # Parse the nested structure (same as get_suno_music_status)
                        record = status_data.get("data", {})
                        response = record.get("response", {})
                        suno_list = response.get("sunoData") or response.get("suno_data") or []
                        
                        if suno_list and len(suno_list) > 0:
                            first_track = suno_list[0]
                            audio_url = first_track.get("audioUrl") or first_track.get("audio_url")
                            stream_url = (
                                first_track.get("stream_audio_url")
                                or first_track.get("streamAudioUrl")
                                or first_track.get("stream_url")
                            )
                            song_title = first_track.get("title") or first_track.get("song_name") or ""

                            if v_id not in venue_queues:
                                venue_queues[v_id] = []
                            queue = venue_queues[v_id]
                            existing = next((s for s in queue if s.get('task_id') == task_id), None)
                            if not existing:
                                existing = {
                                    'task_id': task_id,
                                    # keep existing GPT title if already there; otherwise use Suno title or fallback
                                    'title': song_titles.get(task_id) or song_title or 'Custom Song',
                                    'timestamp': datetime.now().isoformat(),
                                    'added_at': datetime.now().strftime("%H:%M:%S"),
                                    'status': 'generating'
                                }
                                queue.append(existing)

                            # Attach stream URL as soon as available and mark ready for streaming
                            if stream_url:
                                existing['stream_url'] = stream_url
                                existing['status'] = 'ready'

                            # For streaming-only mode we do NOT download audio files.
                            # Once we have either a stream URL or a final audio URL, stop polling this task.
                            if (stream_url or audio_url) and task_id in task_to_venue:
                                print(f"✅ Polling complete for task {task_id}, stopping tracking (stream_url={bool(stream_url)}, audio_url={bool(audio_url)})")
                                del task_to_venue[task_id]
                                save_data()
                            else:
                                print(f"⏳ Task {task_id} still processing (no usable URLs yet, stream_url={bool(stream_url)}, audio_url={bool(audio_url)})")
                        else:
                            print(f"⏳ Task {task_id} still processing (no tracks yet)")
                    else:
                        error_msg = status_data.get("msg", "Unknown error")
                        print(f"❌ Suno API error for task {task_id}: {error_msg}")
                else:
                    print(f"❌ HTTP {status_response.status_code} error polling task {task_id}")
            except Exception as e:
                print(f"❌ Error polling task {task_id}: {e}")
                import traceback
                traceback.print_exc()
                continue
    except Exception as e:
        print(f"❌ Error in check_and_process_pending_tasks: {e}")
        import traceback
        traceback.print_exc()


@app.route('/venue/<venue_id>/queue/next')
def get_next_song(venue_id):
    """Get the next song in queue (for streaming page)"""
    queue = venue_queues.get(venue_id, [])
    if queue:
        return jsonify({
            'status': 'success',
            'song': queue[0]
        })
    return jsonify({
        'status': 'empty',
        'message': 'Queue is empty'
    })


@app.route('/venue/<venue_id>/queue/remove', methods=['POST'])
def remove_song_from_queue(venue_id):
    """Remove a song from queue (optional - songs can stay in queue after playing)"""
    queue = venue_queues.get(venue_id, [])
    data = request.get_json() or {}
    task_id = data.get('task_id')
    
    if task_id:
        # Remove specific song by task_id
        queue[:] = [s for s in queue if s.get('task_id') != task_id]
        return jsonify({
            'status': 'success',
            'message': 'Song removed'
        })
    elif queue:
        # Remove first song (backward compatibility)
        removed = queue.pop(0)
        return jsonify({
            'status': 'success',
            'removed': removed
        })
    return jsonify({
        'status': 'error',
        'message': 'Queue is empty'
    })


@app.route('/send', methods=['POST'])
def send_message():
    try:
        print("=" * 60)
        print("📨 RECEIVED SONG REQUEST")
        print(f"Request method: {request.method}")
        print(f"Content-Type: {request.content_type}")
        print(f"Headers: {dict(request.headers)}")
        
        data = request.get_json()
        if not data:
            print("❌ ERROR: No JSON data received")
            return jsonify({'success': False, 'error': 'No JSON data received'}), 400
        
        print(f"Request data: {data}")
        
        message = data.get('message', '').strip()
        venue_id = data.get('venue_id')  # Optional venue ID
        table_id = data.get('table_id')  # Optional table ID
        genre = data.get('genre', '').strip()

        print(f"Message: {message}")
        print(f"Venue ID: {venue_id}")
        print(f"Table ID: {table_id}")
        print(f"Genre: {genre}")

        if not message:
            print("❌ ERROR: Empty message")
            return jsonify({'success': False, 'error': 'Empty message'}), 400

        # Validate genre if venue_id is provided and genre is specified
        if venue_id and genre:
            load_data()
            if venue_id in venue_metadata:
                allowed_genres = venue_metadata[venue_id].get('allowed_genres', [])
                if allowed_genres and genre not in allowed_genres:
                    print(f"❌ ERROR: Genre '{genre}' not in allowed genres: {allowed_genres}")
                    return jsonify({
                        'success': False, 
                        'error': f'Genre "{genre}" is not allowed for this venue. Allowed genres: {", ".join(allowed_genres)}'
                    }), 400

        # Filter/modify message using GPT API if custom instructions exist
        if venue_id:
            load_data()
            if venue_id in venue_metadata:
                custom_instructions = venue_metadata[venue_id].get('custom_instructions')
                if custom_instructions:
                    print(f"🔍 Filtering message with custom instructions: {custom_instructions}")
                    filtered_result = filter_message_with_gpt(message, custom_instructions)
                    if filtered_result['rejected']:
                        print(f"❌ Message rejected by GPT filter: {filtered_result['reason']}")
                        return jsonify({
                            'success': False,
                            'error': filtered_result['reason'] or 'This song request violates venue rules.'
                        }), 400
                    if filtered_result.get('modified') and filtered_result.get('modified_message'):
                        message = filtered_result['modified_message']
                        print(f"✅ Message modified by GPT: {message}")

        # Save message to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"message_{timestamp}.txt"
        filepath = os.path.join(MESSAGES_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(message)
        print(f"✅ Saved message to: {filepath}")

        # Trigger Suno music generation (non-custom mode, full song with vocals)
        print("🎵 Calling Suno API...")
        music_info = call_suno_generate_music(prompt=message, venue_id=venue_id, table_id=table_id, genre=genre if genre else None)
        print(f"🎵 Suno API response: {music_info}")

        # If we have a task_id and venue, immediately add a "generating" entry to the venue queue
        try:
            if venue_id and isinstance(music_info, dict) and music_info.get('task_id'):
                load_data()
                if venue_id not in venue_queues:
                    venue_queues[venue_id] = []
                # Generate a provisional song title from the user's prompt so the guest sees a real name immediately
                try:
                    provisional_title = generate_song_title_from_prompt(message)
                except Exception as e:
                    print(f"⚠️ Error generating provisional title: {e}")
                    provisional_title = "Custom Song"
                song_entry = {
                    'task_id': music_info['task_id'],
                    'title': provisional_title,
                    'timestamp': datetime.now().isoformat(),
                    'added_at': datetime.now().strftime("%H:%M:%S"),
                    'status': 'generating'
                }
                venue_queues[venue_id].append(song_entry)
                save_data()
                print(f"✅ Added placeholder generating entry for task {music_info['task_id']} in venue {venue_id}")
        except Exception as e:
            print(f"⚠️ Error adding placeholder queue entry: {e}")

        # Return success with timestamp + music generation info
        display_timestamp = datetime.now().strftime("%H:%M:%S")
        response_data = {
            'success': True,
            'timestamp': display_timestamp,
            'message': message,
            'music_generation': music_info,
            'venue_id': venue_id
        }
        print(f"✅ Returning success response: {response_data}")
        print("=" * 60)
        return jsonify(response_data)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print("=" * 60)
        print("❌ ERROR IN /send ENDPOINT")
        print(f"Error: {str(e)}")
        print(f"Traceback:\n{error_trace}")
        print("=" * 60)
        return jsonify({'success': False, 'error': str(e), 'traceback': error_trace}), 500


@app.route('/audio/<filename>')
def serve_audio(filename):
    """Serve audio files from the audio directory"""
    return send_from_directory(AUDIO_DIR, filename)


@app.route('/img/<filename>')
def serve_image(filename):
    """Serve image files from the img directory"""
    try:
        print(f"📸 Serving image: {filename} from {IMG_DIR}")
        print(f"   IMG_DIR exists: {os.path.exists(IMG_DIR)}")
        file_path = os.path.join(IMG_DIR, filename)
        print(f"   File path: {file_path}")
        print(f"   File exists: {os.path.exists(file_path)}")
        if not os.path.exists(file_path):
            print(f"   ❌ File not found! Listing directory: {os.listdir(IMG_DIR) if os.path.exists(IMG_DIR) else 'IMG_DIR does not exist'}")
            return jsonify({'error': f'Image not found: {filename}'}), 404
        return send_from_directory(IMG_DIR, filename)
    except Exception as e:
        import traceback
        error_msg = f"Error serving image {filename}: {str(e)}\n{traceback.format_exc()}"
        print(f"❌ {error_msg}")
        return jsonify({'error': error_msg}), 500


@app.route('/status/<task_id>')
def get_status(task_id):
    """Get status of a music generation task from Suno and download audio if ready."""
    try:
        print(f"=" * 60)
        print(f"STATUS REQUEST for task_id: {task_id}")
        print(f"Current task_audio_map: {task_audio_map}")
        status = get_suno_music_status(task_id)
        print(f"STATUS RESPONSE: {status}")
        print(f"=" * 60)
        return jsonify(status)
    except Exception as e:
        print(f"Error in get_status for {task_id}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/callback/wav', methods=['POST'])
def wav_callback():
    """Handle WAV conversion callback from Suno API"""
    try:
        data = request.get_json()
        print(f"WAV conversion callback received: {data}")
        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"Error processing WAV callback: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/callback/music', methods=['POST'])
def music_callback():
    """
    Handle async callbacks from Suno music generation.
    When we get 'first' or 'complete', download the audio immediately.
    """
    try:
        data = request.get_json()
        callback_data = data.get("data", {})
        callback_type = callback_data.get("callbackType", "")
        # Try both task_id and taskId (Suno uses different formats)
        task_id = callback_data.get("task_id") or callback_data.get("taskId") or ""
        tracks = callback_data.get("data", [])

        print(f"Music generation callback: callbackType={callback_type}, task_id={task_id}")
        print(f"Full callback data: {data}")

        # Check if Suno returned an error
        if data.get("code") != 200:
            error_msg = data.get("msg", "Unknown error")
            print(f"❌ SUNO API ERROR for task {task_id}: {error_msg}")
            # Remove from venue queue tracking if it exists
            if task_id in task_to_venue:
                venue_id = task_to_venue[task_id]
                print(f"   Removing failed task {task_id} from venue {venue_id} tracking")
                del task_to_venue[task_id]
            return jsonify({'success': False, 'error': f'Suno API error: {error_msg}'}), 200

        # When we get 'first' or 'complete', we may have streaming and/or download URLs.
        # For the venue streamer we ONLY care about the streaming URL; we do not download files here.
        if callback_type in ("first", "complete") and tracks:
            first_track = tracks[0]
            audio_url = first_track.get("audio_url") or first_track.get("audioUrl")
            stream_url = (
                first_track.get("stream_audio_url")
                or first_track.get("streamAudioUrl")
                or first_track.get("stream_url")
            )
            # Extract song title if available
            song_title = first_track.get("title") or first_track.get("song_name") or ""
            
            # Update title cache if we have one
            if song_title and task_id:
                song_titles[task_id] = song_title

            # If this task belongs to a venue, update or create the queue entry
            if task_id in task_to_venue:
                venue_id = task_to_venue[task_id]
                if venue_id not in venue_queues:
                    venue_queues[venue_id] = []
                queue = venue_queues[venue_id]
                existing = next((s for s in queue if s.get('task_id') == task_id), None)
                if not existing:
                    existing = {
                        'task_id': task_id,
                        'title': song_titles.get(task_id) or song_title or 'Custom Song',
                        'timestamp': datetime.now().isoformat(),
                        'added_at': datetime.now().strftime("%H:%M:%S"),
                        'status': 'generating'
                    }
                    queue.append(existing)

                # Attach streaming URL as soon as we have it and mark as ready to stream
                if stream_url:
                    existing['stream_url'] = stream_url
                    existing['status'] = 'ready'

                # We don't download full audio files here; this is a pure streaming player.
                # Once we have either a stream URL or a final audio URL, stop polling this task.
                if (stream_url or audio_url) and task_id in task_to_venue:
                    print(
                        f"✅ Callback complete for task {task_id}, stopping polling "
                        f"(stream_url={bool(stream_url)}, audio_url={bool(audio_url)})"
                    )
                    del task_to_venue[task_id]
                
                save_data()

                # Update table request status if this was from a table
                for table_id, requests in table_requests.items():
                    for req in requests:
                        if req['task_id'] == task_id:
                            req['status'] = 'completed'
                            print(f"✅ Marked table {table_id} request as completed")
                save_data()  # Save updated table request status

        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"Error processing music callback: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


def filter_message_with_gpt(message: str, custom_instructions: str):
    """
    Use GPT API to filter/modify song requests based on custom instructions.
    Returns: {'rejected': bool, 'reason': str or None, 'modified': bool, 'modified_message': str or None}
    """
    if not OPENAI_API_KEY:
        print("⚠️ OPENAI_API_KEY not set, skipping GPT filtering")
        return {'rejected': False, 'reason': None, 'modified': False, 'modified_message': None}
    
    try:
        prompt = f"""You are a gatekeeper for a music venue's song request system. The venue has set these custom rules:

{custom_instructions}

A guest has submitted this song request: "{message}"

Your task:
1. If the request violates the rules, respond with JSON: {{"rejected": true, "reason": "explanation of why it was rejected"}}
2. If the request is acceptable but needs modification to comply with rules, respond with JSON: {{"rejected": false, "modified": true, "modified_message": "the modified request"}}
3. If the request is fine as-is, respond with JSON: {{"rejected": false, "modified": false}}

Only respond with valid JSON, nothing else."""

        headers = {
            'Authorization': f'Bearer {OPENAI_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'model': 'gpt-3.5-turbo',
            'messages': [
                {'role': 'system', 'content': 'You are a helpful assistant that filters song requests based on venue rules. Always respond with valid JSON only.'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.3,
            'max_tokens': 200
        }
        
        response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content'].strip()
            
            # Try to parse JSON response
            try:
                # Remove markdown code blocks if present
                if content.startswith('```'):
                    content = content.split('```')[1]
                    if content.startswith('json'):
                        content = content[4:]
                    content = content.strip()
                
                parsed = json.loads(content)
                return {
                    'rejected': parsed.get('rejected', False),
                    'reason': parsed.get('reason'),
                    'modified': parsed.get('modified', False),
                    'modified_message': parsed.get('modified_message')
                }
            except json.JSONDecodeError:
                print(f"⚠️ GPT returned invalid JSON: {content}")
                # If GPT doesn't return valid JSON, allow the request through
                return {'rejected': False, 'reason': None, 'modified': False, 'modified_message': None}
        else:
            print(f"⚠️ GPT API error: {response.status_code} - {response.text}")
            return {'rejected': False, 'reason': None, 'modified': False, 'modified_message': None}
    except Exception as e:
        print(f"⚠️ Error calling GPT API: {e}")
        import traceback
        traceback.print_exc()
        # On error, allow request through (fail open)
        return {'rejected': False, 'reason': None, 'modified': False, 'modified_message': None}


def generate_song_title_from_prompt(prompt_text: str) -> str:
    """
    Generate a short, user-friendly song title from a guest's prompt.
    Uses GPT when OPENAI_API_KEY is available; otherwise falls back to a simple heuristic.
    """
    base_fallback = "Custom Song"
    if not prompt_text:
        return base_fallback

    # Simple fallback: trim the prompt and format it
    def heuristic_title(p: str) -> str:
        trimmed = p.strip().replace("\n", " ")
        if len(trimmed) > 80:
            trimmed = trimmed[:77].rsplit(" ", 1)[0] + "..."
        return trimmed or base_fallback

    if not OPENAI_API_KEY:
        return heuristic_title(prompt_text)

    try:
        headers = {
            'Authorization': f'Bearer {OPENAI_API_KEY}',
            'Content-Type': 'application/json'
        }
        prompt = (
            "You are naming songs for a bar's live AI music system. "
            "Given what a guest requested, create a short, catchy song title (max 40 characters). "
            "Return ONLY the title text, no quotes, no extra words.\n\n"
            f"Guest request: {prompt_text}"
        )
        payload = {
            'model': 'gpt-3.5-turbo',
            'messages': [
                {'role': 'system', 'content': 'You generate short, catchy song titles.'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.6,
            'max_tokens': 30
        }
        resp = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=payload, timeout=8)
        if resp.status_code != 200:
            print(f"⚠️ GPT title API error: {resp.status_code} - {resp.text[:200]}")
            return heuristic_title(prompt_text)
        data = resp.json()
        content = (data.get('choices') or [{}])[0].get('message', {}).get('content', '') or ''
        title = content.strip().strip('"').strip("'")
        if not title:
            return heuristic_title(prompt_text)
        if len(title) > 60:
            title = title[:57].rsplit(" ", 1)[0] + "..."
        return title
    except Exception as e:
        print(f"⚠️ Error generating song title with GPT: {e}")
        import traceback
        traceback.print_exc()
        return heuristic_title(prompt_text)


def call_suno_generate_music(prompt: str, venue_id: str = None, table_id: str = None, genre: str = None):
    """
    Call Suno /api/v1/generate to start music generation.

    We use NON-CUSTOM mode so:
    - Suno generates full songs with vocals (instrumental = False)
    - Lyrics are auto-generated from the prompt
    - We can just describe the vibe/genre in plain English
    """
    print("=" * 60)
    print("🎵 call_suno_generate_music called")
    print(f"   prompt: {prompt}")
    print(f"   venue_id: {venue_id}")
    print(f"   table_id: {table_id}")
    print(f"   genre: {genre}")
    print(f"   SUNO_API_KEY exists: {bool(SUNO_API_KEY)}")
    print(f"   SUNO_API_BASE: {SUNO_API_BASE}")
    
    if not SUNO_API_KEY:
        print("❌ ERROR: SUNO_API_KEY not configured")
        return {
            'status': 'disabled',
            'message': 'SUNO_API_KEY not configured on server'
        }

    try:
        # Use provided genre, or detect from message, or leave empty
        if not genre:
            genre = detect_genre(prompt)
            print(f"   Detected genre: {genre}")
        
        # Get venue settings for explicit content
        explicit_content = None
        if venue_id and venue_id in venue_metadata:
            explicit_content = venue_metadata[venue_id].get('explicit_content')
        
        # Build prompt with genre
        if genre:
            # Strongly hint the genre to Suno
            final_prompt = f"Make a {genre} song about: {prompt}"
        else:
            # Let Suno decide, but still ask for a full vocal song
            final_prompt = f"Make a full vocal song about: {prompt}"

        # Add explicit/non-explicit instruction ONLY if setting is configured
        if explicit_content is not None:
            if explicit_content:
                final_prompt += " Use explicit lyrics."
            else:
                final_prompt += " Use clean, non-explicit lyrics only."
            print(f"   Explicit content setting: {'explicit' if explicit_content else 'non-explicit'}")

        final_prompt = final_prompt[:500]  # non-custom mode prompt limit
        print(f"   Final prompt: {final_prompt}")

        url = f"{SUNO_API_BASE}/api/v1/generate"
        callback_base_url = get_callback_base_url()
        print(f"   API URL: {url}")
        print(f"   Callback base URL: {callback_base_url}")
        
        payload = {
            "customMode": False,          # non-custom mode
            "instrumental": False,        # we want vocals (not instrumental)
            "model": "V5",
            "prompt": final_prompt,
        }
        # Only add callback URL if we have a public URL (not localhost)
        if callback_base_url:
            payload["callBackUrl"] = f"{callback_base_url}/callback/music"
            print(f"   Callback URL added: {payload['callBackUrl']}")
        else:
            print("   ⚠️ WARNING: No callback URL available")
        
        headers = {
            "Authorization": f"Bearer {SUNO_API_KEY}",
            "Content-Type": "application/json",
        }
        print(f"   Payload: {payload}")
        print(f"   Headers: {dict(headers)}")

        print("   📡 Sending request to Suno API...")
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        print(f"   📡 Response status: {resp.status_code}")
        print(f"   📡 Response text (first 500 chars): {resp.text[:500]}")
        
        data = resp.json()
        print(f"   📥 Parsed response: {data}")

        if resp.status_code != 200 or data.get("code") != 200:
            error_msg = data.get("msg") or f"HTTP {resp.status_code}"
            print(f"   ❌ Suno API Error: {error_msg}")
            return {
                'status': 'error',
                'message': error_msg
            }

        task_id = (data.get("data") or {}).get("taskId")
        print(f"   🎯 Task ID: {task_id}")
        
        if not task_id:
            print("   ❌ ERROR: No taskId returned from Suno")
            return {
                'status': 'error',
                'message': 'No taskId returned from Suno'
            }

        # If venue_id is provided, store the mapping for later queue addition
        if venue_id:
            task_to_venue[task_id] = venue_id
            print(f"   ✅ Mapped task {task_id} to venue {venue_id}")
            save_data()  # Save mapping immediately
        else:
            print("   ⚠️ WARNING: No venue_id provided - song won't be added to queue!")
        
        # If table_id is provided, track the request
        if table_id:
            if table_id not in table_requests:
                table_requests[table_id] = []
            table_requests[table_id].append({
                'task_id': task_id,
                'timestamp': datetime.now().isoformat(),
                'status': 'processing'
            })
            print(f"   ✅ Tracked request for table {table_id}")

        result = {
            'status': 'processing',
            'task_id': task_id,
            'message': 'Music generation started',
            'venue_id': venue_id,
            'table_id': table_id
        }
        print(f"   ✅ Success! Returning: {result}")
        print("=" * 60)
        return result
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print("=" * 60)
        print("❌ ERROR IN call_suno_generate_music")
        print(f"   Error: {str(e)}")
        print(f"   Traceback:\n{error_trace}")
        print("=" * 60)
        return {
            'status': 'error',
            'message': str(e)
        }


def detect_genre(text: str) -> str:
    """
    Very simple genre detector based on keywords in the user's message.
    Returns a short genre name or empty string if we can't guess.
    """
    t = text.lower()

    if "country" in t:
        return "country"
    if "rap" in t or "hip hop" in t or "hip-hop" in t:
        return "rap"
    if "rock" in t:
        return "rock"
    if "pop" in t:
        return "pop"
    if "jazz" in t:
        return "jazz"
    if "lofi" in t or "lo-fi" in t:
        return "lofi"
    if "edm" in t or "electronic" in t or "house" in t:
        return "electronic"
    if "r&b" in t or "rnb" in t:
        return "r&b"
    if "metal" in t:
        return "metal"
    if "classical" in t or "orchestral" in t:
        return "classical"

    # No obvious genre keyword found
    return ""


def get_suno_music_status(task_id: str):
    """
    Check music generation status via /api/v1/generate/record-info.
    Also check if callback already downloaded the audio (faster path).
    """
    print(f"get_suno_music_status called for task_id: {task_id}")
    print(f"Current task_audio_map contents: {task_audio_map}")
    
    # First check if callback already downloaded it
    if task_id in task_audio_map:
        filename = task_audio_map[task_id]
        file_path = os.path.join(AUDIO_DIR, filename)
        print(f"Found task {task_id} in map with filename: {filename}")
        if os.path.exists(file_path):
            print(f"File exists at {file_path}, returning success")
            return {
                'status': 'success',
                'message': 'Music generated successfully!',
                'audio_file': filename
            }
        else:
            print(f"File NOT found at {file_path} even though in map! Will try fallback scan.")
    
    # ALWAYS scan audio directory - this is the most reliable way
    # Also try partial matches in case task_id format differs
    try:
        if os.path.exists(AUDIO_DIR):
            all_files = [f for f in os.listdir(AUDIO_DIR) if f.endswith(('.mp3', '.wav'))]
            print(f"Scanning audio directory. Found {len(all_files)} audio files: {all_files}")
            
            # Try exact match first
            for file in all_files:
                if file.startswith(task_id + "_"):
                    file_path = os.path.join(AUDIO_DIR, file)
                    if os.path.exists(file_path):
                        print(f"Found audio file by exact task_id match: {file}")
                        task_audio_map[task_id] = file
                        return {
                            'status': 'success',
                            'message': 'Music generated successfully!',
                            'audio_file': file
                        }
            
            # If no exact match, try partial match (last part of task_id)
            # Sometimes Suno uses shortened IDs in callbacks
            task_id_parts = task_id.split('-') if '-' in task_id else [task_id]
            if len(task_id_parts) > 0:
                last_part = task_id_parts[-1]
                for file in all_files:
                    if last_part in file and file.endswith(('.mp3', '.wav')):
                        file_path = os.path.join(AUDIO_DIR, file)
                        if os.path.exists(file_path):
                            print(f"Found audio file by partial task_id match: {file}")
                            task_audio_map[task_id] = file
                            return {
                                'status': 'success',
                                'message': 'Music generated successfully!',
                                'audio_file': file
                            }
            
            # Last resort: return the most recently modified file
            if all_files:
                # Sort by modification time, most recent first
                files_with_time = []
                for file in all_files:
                    file_path = os.path.join(AUDIO_DIR, file)
                    if os.path.exists(file_path):
                        mtime = os.path.getmtime(file_path)
                        files_with_time.append((mtime, file))
                
                if files_with_time:
                    files_with_time.sort(reverse=True)  # Most recent first
                    most_recent_file = files_with_time[0][1]
                    file_path = os.path.join(AUDIO_DIR, most_recent_file)
                    print(f"Using most recent audio file as fallback: {most_recent_file}")
                    task_audio_map[task_id] = most_recent_file
                    return {
                        'status': 'success',
                        'message': 'Music generated successfully!',
                        'audio_file': most_recent_file
                    }
    except Exception as e:
        print(f"Error scanning audio directory: {e}")
        import traceback
        traceback.print_exc()
    
    # If we got here, no file was found in the directory
    # This should rarely happen if files are being downloaded
    print(f"WARNING: No audio file found for task_id {task_id} after scanning directory")

    # Otherwise poll Suno API
    if not SUNO_API_KEY:
        return {
            'status': 'disabled',
            'message': 'SUNO_API_KEY not configured on server'
        }

    url = f"{SUNO_API_BASE}/api/v1/generate/record-info"
    headers = {
        "Authorization": f"Bearer {SUNO_API_KEY}",
        "Content-Type": "application/json",
    }
    params = {"taskId": task_id}

    resp = requests.get(url, headers=headers, params=params, timeout=20)
    data = resp.json()

    if resp.status_code != 200 or data.get("code") != 200:
        return {
            'status': 'error',
            'message': data.get("msg") or f"HTTP {resp.status_code}"
        }

    record = (data.get("data") or {})
    response = record.get("response") or {}
    suno_list = response.get("sunoData") or response.get("suno_data") or []

    if not suno_list:
        # Still processing
        return {
            'status': 'processing',
            'message': 'Music is being generated...'
        }

    first = suno_list[0]
    audio_url = first.get("audioUrl") or first.get("audio_url")
    if not audio_url:
        return {
            'status': 'processing',
            'message': 'Music is being generated...'
        }

    # Download audio to local file (mp3)
    filename = download_audio_file(audio_url, prefix=task_id)
    if filename:
        task_audio_map[task_id] = filename

    return {
        'status': 'success',
        'message': 'Music generated successfully!',
        'audio_file': filename
    }


def download_audio_file(audio_url: str, prefix: str = "") -> str:
    """Download an audio file to AUDIO_DIR and return the local filename."""
    try:
        parsed = urlparse(audio_url)
        base_name = os.path.basename(parsed.path) or "track.mp3"
        if not base_name.lower().endswith(".mp3"):
            base_name += ".mp3"

        if prefix:
            filename = f"{prefix}_{base_name}"
        else:
            filename = base_name

        local_path = os.path.join(AUDIO_DIR, filename)

        # Skip download if we already have it
        if os.path.exists(local_path):
            print(f"File already exists, skipping download: {filename}")
            return filename

        print(f"Downloading {audio_url} to {local_path}")
        with requests.get(audio_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

        # Verify file was written
        if os.path.exists(local_path):
            file_size = os.path.getsize(local_path)
            print(f"Download complete: {filename} ({file_size} bytes)")
            return filename
        else:
            print(f"ERROR: File was not created at {local_path}")
            return ""
    except Exception as e:
        print(f"Error downloading audio file: {e}")
        return ""


def get_local_ip():
    """Get the local IP address of this machine"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.route('/debug/audio')
def debug_audio():
    """Debug endpoint to see what's in the audio directory and task map"""
    try:
        audio_files = []
        if os.path.exists(AUDIO_DIR):
            audio_files = [f for f in os.listdir(AUDIO_DIR) if f.endswith(('.mp3', '.wav'))]
            # Get file details
            file_details = []
            for f in audio_files:
                file_path = os.path.join(AUDIO_DIR, f)
                if os.path.exists(file_path):
                    file_details.append({
                        'name': f,
                        'size': os.path.getsize(file_path),
                        'mtime': os.path.getmtime(file_path)
                    })
        
        return jsonify({
            'audio_files': audio_files,
            'file_details': file_details,
            'task_audio_map': task_audio_map,
            'audio_dir': AUDIO_DIR,
            'audio_dir_exists': os.path.exists(AUDIO_DIR)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/songs')
def show_songs():
    """Display all saved songs with audio players"""
    try:
        audio_files = []
        if os.path.exists(AUDIO_DIR):
            # Get all audio files with their metadata
            files_with_info = []
            for filename in os.listdir(AUDIO_DIR):
                if filename.endswith(('.mp3', '.wav')):
                    file_path = os.path.join(AUDIO_DIR, filename)
                    if os.path.exists(file_path):
                        file_size = os.path.getsize(file_path)
                        mtime = os.path.getmtime(file_path)
                        
                        # Try to find title from task_id in filename
                        title = None
                        # Extract task_id from filename (format: task_id_rest.mp3)
                        if '_' in filename:
                            potential_task_id = filename.split('_')[0]
                            if potential_task_id in song_titles:
                                title = song_titles[potential_task_id]
                        
                        # If no title found, create a clean name from filename
                        if not title:
                            # Remove task_id prefix and file extension
                            clean_name = filename
                            if '_' in filename:
                                clean_name = '_'.join(filename.split('_')[1:])
                            if '.' in clean_name:
                                clean_name = clean_name.rsplit('.', 1)[0]
                            # Replace underscores/hyphens with spaces and title case
                            clean_name = clean_name.replace('_', ' ').replace('-', ' ').strip()
                            if clean_name:
                                title = clean_name.title()
                        
                        files_with_info.append({
                            'filename': filename,
                            'title': title or filename,  # Fallback to filename if no title
                            'size': file_size,
                            'size_mb': round(file_size / (1024 * 1024), 2),
                            'modified': datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                            'modified_timestamp': mtime
                        })
            
            # Sort by most recent first
            files_with_info.sort(key=lambda x: x['modified_timestamp'], reverse=True)
            audio_files = files_with_info
        
        return render_template('songs.html', songs=audio_files)
    except Exception as e:
        print(f"Error loading songs: {e}")
        return render_template('songs.html', songs=[], error=str(e))


@app.route('/qr')
def show_qr():
    """Display QR code page"""
    base_url = get_base_url() or ''
    return render_template('qr.html', url=base_url)


@app.route('/onboarding', methods=['GET'])
@require_login
def onboarding():
    """First-time setup wizard for non-admin users."""
    user_email = session.get('user_id')
    global users
    users = load_users()
    user_record = users.get(user_email, {})

    # Admins and users who already completed onboarding go straight to venues
    if user_record.get('is_admin', False) or user_record.get('onboarding_completed', False):
        return redirect(url_for('venues'))

    base_url = get_base_url() or ''
    return render_template('onboarding.html', base_url=base_url, user_name=session.get('user_name', 'User'))


@app.route('/onboarding/complete', methods=['POST'])
@require_login
def onboarding_complete():
    """Mark onboarding as completed and store QR preference."""
    user_email = session.get('user_id')
    data = request.get_json() or {}
    qr_mode = data.get('qr_mode')

    global users
    users = load_users()
    if user_email in users:
        users[user_email]['onboarding_completed'] = True
        if qr_mode in ('single', 'tables'):
            users[user_email]['default_qr_mode'] = qr_mode
        save_users(users)

    redirect_url = url_for('venues')
    if request.is_json:
        return jsonify({'success': True, 'redirect': redirect_url})
    return redirect(redirect_url)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """User signup page"""
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form.to_dict()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '').strip()
        name = data.get('name', '').strip()
        
        if not email or not password:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Email and password are required'}), 400
            return render_template('signup.html', error='Email and password are required')
        
        global users
        users = load_users()
        
        # Prevent signup with admin email
        if email.lower() == ADMIN_EMAIL.lower():
            if request.is_json:
                return jsonify({'success': False, 'error': 'This email is reserved'}), 400
            return render_template('signup.html', error='This email is reserved')
        
        if email in users:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Email already registered'}), 400
            return render_template('signup.html', error='Email already registered')
        
        # Create new user
        password_hash = hash_password(password)
        users[email] = {
            'email': email,
            'name': name or email.split('@')[0],
            'password_hash': password_hash,
            'created_at': datetime.now().isoformat(),
            # New users should go through the guided setup wizard on first login
            'onboarding_completed': False,
            # Preference for how QR codes should work by default ('single' or 'tables')
            'default_qr_mode': None
        }
        print(f"🔐 Creating user '{email}' with password hash: {password_hash[:20]}...")
        print(f"   Users dict now has {len(users)} user(s): {list(users.keys())}")
        save_users(users)
        # Reload to verify it was saved
        users = load_users()
        if email in users:
            print(f"✅ User '{email}' created and saved successfully - verified in file")
        else:
            print(f"❌ WARNING: User '{email}' was not found after save! This is a critical error!")
        
        # Check if user wants to stay logged in
        remember_me = data.get('remember_me', True)  # Default to True for better UX
        
        # Log in the user
        session.permanent = remember_me  # Make session permanent if remember_me is True
        session['user_id'] = email
        session['user_name'] = users[email]['name']
        session['is_admin'] = users[email].get('is_admin', False)
        session['remember_me'] = remember_me  # Store preference in session
        
        # Mark session as modified to ensure it's saved
        session.modified = True
        
        # After signup, send everyone to venues; first-time users will see the in-dashboard wizard modal
        if request.is_json:
            redirect_url = url_for('venues')
            return jsonify({
                'success': True, 
                'message': 'Account created successfully',
                'redirect': redirect_url
            })
        
        return redirect(url_for('venues'))
    
    # Pre-fill from query string when coming from landing-page demo
    prefill_venue_name = request.args.get('venue_name', '').strip()
    prefill_email = request.args.get('email', '').strip()
    prefill_name = request.args.get('name', '').strip()
    if prefill_venue_name:
        # Stash for onboarding wizard to use as the default venue name
        session['initial_venue_name'] = prefill_venue_name
        session['prefill_venue_name'] = prefill_venue_name
    return render_template('signup.html', prefill_venue_name=prefill_venue_name, prefill_email=prefill_email, prefill_name=prefill_name)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page"""
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form.to_dict()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '').strip()
        
        if not email or not password:
            if request.is_json:
                return jsonify({'success': False, 'error': 'Email and password are required'}), 400
            return render_template('login.html', error='Email and password are required')
        
        global users
        users = load_users()
        
        if email not in users:
            print(f"❌ Login failed: Email '{email}' not found in users")
            print(f"   Available users: {list(users.keys())}")
            if request.is_json:
                return jsonify({'success': False, 'error': 'Invalid email or password'}), 401
            return render_template('login.html', error='Invalid email or password')
        
        stored_hash = users[email].get('password_hash')
        if not stored_hash:
            print(f"❌ Login failed: No password hash found for user '{email}'")
            if request.is_json:
                return jsonify({'success': False, 'error': 'Invalid email or password'}), 401
            return render_template('login.html', error='Invalid email or password')
        
        # Debug logging
        password_hash = hash_password(password)
        print(f"🔍 Login attempt for '{email}'")
        print(f"   Stored hash: {stored_hash[:20]}...")
        print(f"   Computed hash: {password_hash[:20]}...")
        print(f"   Match: {password_hash == stored_hash}")
        
        if not verify_password(password, stored_hash):
            print(f"❌ Login failed: Password mismatch for '{email}'")
            if request.is_json:
                return jsonify({'success': False, 'error': 'Invalid email or password'}), 401
            return render_template('login.html', error='Invalid email or password')
        
        print(f"✅ Login successful for '{email}'")
        
        # Check if user wants to stay logged in
        remember_me = data.get('remember_me', True)  # Default to True for better UX
        
        # Log in the user
        session.permanent = remember_me  # Make session permanent if remember_me is True
        session['user_id'] = email
        session['user_name'] = users[email]['name']
        session['is_admin'] = users[email].get('is_admin', False)
        session['remember_me'] = remember_me  # Store preference in session
        
        # Mark session as modified to ensure it's saved
        session.modified = True
        
        if request.is_json:
            return jsonify({
                'success': True, 
                'message': 'Logged in successfully',
                'redirect': url_for('venues')
            })
        return redirect(url_for('venues'))
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    """Logout user"""
    session.pop('user_id', None)
    session.pop('user_name', None)
    return redirect(url_for('landing'))


@app.route('/venues')
@require_login
def venues():
    """Venue management page - shows all venues for admins, one venue for normal users"""
    user_email = session.get('user_id')
    is_admin = session.get('is_admin', False)
    
    # For admins, show all venues. For normal users, show only their venue
    if is_admin:
        # Admin sees all venues - reload data and get all venue IDs
        load_data()
        all_venue_ids = list(venue_metadata.keys())
        print(f"🔍 Admin user - loading all {len(all_venue_ids)} venues: {all_venue_ids}")
        base_url = get_base_url() or ''
        return render_template(
            'admin_venues.html',
            base_url=base_url,
            user_name=session.get('user_name', 'User'),
            is_admin=True,
            user_venue_ids=all_venue_ids,
            venue_metadata=venue_metadata
        )
    else:
        # Normal user sees only their venue; onboarding wizard (if any) is shown as a modal on top of this page.
        global users
        users = load_users()
        user_record = users.get(user_email, {})
        show_onboarding = not user_record.get('onboarding_completed', False)
        initial_venue_name = session.get('initial_venue_name') or session.get('prefill_venue_name') or session.get('user_name', 'My Venue')
        # RELOAD data before checking to ensure we have latest
        load_data()
        user_venue_ids = venue_owners.get(user_email, [])
        print(f"🔍 User {user_email} has venues: {user_venue_ids}")
        print(f"   All venue_owners: {dict(venue_owners)}")
        print(f"   All venue_metadata keys: {list(venue_metadata.keys())}")
        # Also check venue_metadata for venues owned by this user (backup check)
        for venue_id, metadata in venue_metadata.items():
            if metadata.get('owner_email') == user_email and venue_id not in user_venue_ids:
                print(f"   ⚠️ Found venue {venue_id} owned by {user_email} in metadata but not in venue_owners - fixing...")
                if user_email not in venue_owners:
                    venue_owners[user_email] = []
                venue_owners[user_email].append(venue_id)
                user_venue_ids.append(venue_id)
                save_data()  # Save the fix
        print(f"   ✅ Final user_venue_ids: {user_venue_ids}")
        if not user_venue_ids and not show_onboarding:
            # If no venue exists and onboarding is already complete, auto-create a default venue
            import uuid
            venue_id = str(uuid.uuid4())[:8]
            all_genres = ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical']
            venue_metadata[venue_id] = {
                'name': initial_venue_name,
                'created_at': datetime.now().isoformat(),
                'logo_path': None,
                'qr_background': None,
                'allowed_genres': all_genres,
                'owner_email': user_email
            }
            venue_queues[venue_id] = []
            venue_owners[user_email] = [venue_id]
            user_venue_ids = [venue_id]
            print(f"💾 Auto-created venue {venue_id} for user {user_email}, saving...")
            save_data()  # Save new venue data
            print(f"✅ Auto-created venue saved")
        
        base_url = get_base_url() or ''
        return render_template(
            'admin_venues.html',
            base_url=base_url,
            user_name=session.get('user_name', 'User'),
            is_admin=False,
            user_venue_ids=user_venue_ids,
            show_onboarding=show_onboarding,
            initial_venue_name=initial_venue_name,
            venue_metadata=venue_metadata
        )


@app.route('/admin/genres')
@require_login
def admin_genres():
    """Admin page to manage genres for venues"""
    # Get all venues with their metadata
    venues_list = []
    for venue_id, metadata in venue_metadata.items():
        venues_list.append({
            'venue_id': venue_id,
            'name': metadata.get('name', f'Venue {venue_id}'),
            'allowed_genres': metadata.get('allowed_genres', ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical'])
        })
    
    # Sort by name
    venues_list.sort(key=lambda x: x['name'])
    
    base_url = get_base_url() or ''
    return render_template('admin_genres.html', 
                         base_url=base_url, 
                         user_name=session.get('user_name', 'User'),
                         venues=venues_list)




@app.route('/venue/<venue_id>/update', methods=['POST'])
@require_login
def update_venue(venue_id):
    """Update venue name"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        if name:
            venue_metadata[venue_id]['name'] = name
            save_data()  # Save updated venue name
        
        return jsonify({
            'success': True,
            'venue_id': venue_id,
            'name': venue_metadata[venue_id]['name']
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue/<venue_id>/genres', methods=['GET'])
@require_login
def get_venue_genres(venue_id):
    """Get allowed genres for a venue"""
    try:
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        allowed_genres = venue_metadata[venue_id].get('allowed_genres', ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical'])
        all_genres = ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical']
        
        return jsonify({
            'success': True,
            'venue_id': venue_id,
            'allowed_genres': allowed_genres,
            'all_genres': all_genres
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue/<venue_id>/genres', methods=['POST'])
@require_login
def update_venue_genres(venue_id):
    """Update allowed genres for a venue"""
    try:
        data = request.get_json()
        allowed_genres = data.get('allowed_genres', [])
        
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        # Validate genres
        all_genres = ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical']
        if not isinstance(allowed_genres, list):
            return jsonify({'success': False, 'error': 'allowed_genres must be a list'}), 400
        
        # Filter to only valid genres
        allowed_genres = [g for g in allowed_genres if g in all_genres]
        
        venue_metadata[venue_id]['allowed_genres'] = allowed_genres
        save_data()  # Save updated genres
        
        return jsonify({
            'success': True,
            'venue_id': venue_id,
            'allowed_genres': allowed_genres
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/settings')
@require_login
def settings():
    """Settings page for venue configuration"""
    user_email = session.get('user_id')
    is_admin = session.get('is_admin', False)
    
    load_data()
    
    # Get user's venues
    if is_admin:
        # Admin sees all venues
        user_venue_ids = list(venue_metadata.keys())
    else:
        user_venue_ids = venue_owners.get(user_email, [])
    
    # If user has no venues, redirect to venues page
    if not user_venue_ids:
        return redirect(url_for('venues'))
    
    # Get settings for first venue (or allow selection)
    venue_id = user_venue_ids[0] if user_venue_ids else None
    if venue_id and venue_id in venue_metadata:
        metadata = venue_metadata[venue_id]
        allowed_genres = metadata.get('allowed_genres', ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical'])
        explicit_content = metadata.get('explicit_content', None)  # None = not set, True = explicit, False = non-explicit
        custom_instructions = metadata.get('custom_instructions', None)
    else:
        allowed_genres = ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical']
        explicit_content = None
        custom_instructions = None
    
    all_genres = ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical']
    
    return render_template('settings.html', 
                         venue_id=venue_id,
                         user_venue_ids=user_venue_ids,
                         allowed_genres=allowed_genres,
                         explicit_content=explicit_content,
                         custom_instructions=custom_instructions,
                         all_genres=all_genres,
                         user_name=session.get('user_name', 'User'),
                         is_admin=is_admin)


@app.route('/venue/<venue_id>/settings', methods=['POST'])
@require_login
def update_venue_settings(venue_id):
    """Update venue settings (genres, explicit content, and custom instructions)"""
    try:
        data = request.get_json()
        allowed_genres = data.get('allowed_genres', [])
        explicit_content = data.get('explicit_content', None)  # None, True, or False
        custom_instructions = data.get('custom_instructions', None)  # String or None
        
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        # Validate genres
        all_genres = ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical']
        if not isinstance(allowed_genres, list):
            return jsonify({'success': False, 'error': 'allowed_genres must be a list'}), 400
        
        # Filter to only valid genres
        allowed_genres = [g for g in allowed_genres if g in all_genres]
        
        # Update settings
        venue_metadata[venue_id]['allowed_genres'] = allowed_genres
        if explicit_content is not None:
            venue_metadata[venue_id]['explicit_content'] = explicit_content
        else:
            # Remove the setting if None (not set)
            venue_metadata[venue_id].pop('explicit_content', None)
        
        # Update custom instructions
        if custom_instructions:
            venue_metadata[venue_id]['custom_instructions'] = custom_instructions.strip()
        else:
            venue_metadata[venue_id].pop('custom_instructions', None)
        
        save_data()
        
        return jsonify({
            'success': True,
            'venue_id': venue_id,
            'allowed_genres': allowed_genres,
            'explicit_content': explicit_content,
            'custom_instructions': custom_instructions
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue/<venue_id>/tables', methods=['POST'])
@require_login
def create_table(venue_id):
    """Create a new table for a venue"""
    try:
        data = request.get_json()
        table_name = data.get('name', '').strip()
        
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        import uuid
        table_id = str(uuid.uuid4())[:8]
        
        if venue_id not in venue_tables:
            venue_tables[venue_id] = {}
        
        base_url = get_base_url()
        submit_url = f"{base_url}/venue/{venue_id}/table/{table_id}/submit"
        
        venue_tables[venue_id][table_id] = {
            'name': table_name or f'Table {table_id}',
            'created_at': datetime.now().isoformat(),
            'submit_url': submit_url,
            'qr_code': f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={submit_url}"
        }
        
        # Initialize empty request list for this table
        table_requests[table_id] = []
        
        return jsonify({
            'success': True,
            'table_id': table_id,
            'name': venue_tables[venue_id][table_id]['name'],
            'submit_url': submit_url,
            'qr_code': venue_tables[venue_id][table_id]['qr_code']
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue/<venue_id>/tables', methods=['GET'])
@require_login
def get_venue_tables(venue_id):
    """Get all tables for a venue"""
    try:
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        tables = venue_tables.get(venue_id, {})
        tables_list = []
        for table_id, table_data in tables.items():
            # Get request count for this table
            request_count = len(table_requests.get(table_id, []))
            tables_list.append({
                'table_id': table_id,
                'name': table_data['name'],
                'created_at': table_data['created_at'],
                'submit_url': table_data['submit_url'],
                'qr_code': table_data['qr_code'],
                'request_count': request_count
            })
        
        return jsonify({
            'success': True,
            'venue_id': venue_id,
            'tables': tables_list
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue/<venue_id>/table/<table_id>/update', methods=['POST'])
@require_login
def update_table_name(venue_id, table_id):
    """Update a table's name"""
    try:
        user_email = session.get('user_id')
        is_admin = session.get('is_admin', False)
        
        # Check if user owns this venue or is admin
        if not is_admin:
            user_venues = venue_owners.get(user_email, [])
            if venue_id not in user_venues:
                return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        if venue_id not in venue_tables or table_id not in venue_tables[venue_id]:
            return jsonify({'success': False, 'error': 'Table not found'}), 404
        
        data = request.get_json()
        new_name = data.get('name', '').strip()
        
        if not new_name:
            return jsonify({'success': False, 'error': 'Table name cannot be empty'}), 400
        
        # Update the table name
        venue_tables[venue_id][table_id]['name'] = new_name
        save_data()
        
        return jsonify({
            'success': True,
            'table_id': table_id,
            'name': new_name
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue/<venue_id>/table/<table_id>/submit')
def table_submit(venue_id, table_id):
    """Submission page for a specific table"""
    # Get allowed genres for this venue, default to all if not set
    allowed_genres = venue_metadata.get(venue_id, {}).get('allowed_genres', ['country', 'rap', 'rock', 'pop', 'jazz', 'lofi', 'electronic', 'r&b', 'metal', 'classical'])
    return render_template('venue_submit.html', venue_id=venue_id, table_id=table_id, allowed_genres=allowed_genres)


@app.route('/venue/<venue_id>/live-tables')
@require_login
def live_tables(venue_id):
    """Live tables view showing all tables and their request status"""
    return render_template('live_tables.html', venue_id=venue_id, user_name=session.get('user_name', 'User'))


@app.route('/venue/<venue_id>/live-tables/status')
@require_login
def get_live_tables_status(venue_id):
    """Get live status of all tables for a venue"""
    try:
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        tables = venue_tables.get(venue_id, {})
        tables_status = []
        
        for table_id, table_data in tables.items():
            # Get recent requests (last 10 minutes)
            recent_requests = []
            if table_id in table_requests:
                cutoff_time = datetime.now().timestamp() - 600  # 10 minutes ago
                for req in table_requests[table_id]:
                    req_time = datetime.fromisoformat(req['timestamp']).timestamp()
                    if req_time > cutoff_time:
                        recent_requests.append(req)
            
            # Check if there are any active/pending requests
            has_active_request = any(
                req.get('status') in ['processing', 'pending'] 
                for req in recent_requests
            )
            
            tables_status.append({
                'table_id': table_id,
                'name': table_data['name'],
                'has_active_request': has_active_request,
                'recent_request_count': len(recent_requests),
                'last_request_time': recent_requests[-1]['timestamp'] if recent_requests else None
            })
        
        return jsonify({
            'success': True,
            'venue_id': venue_id,
            'venue_name': venue_metadata[venue_id].get('name', f'Venue {venue_id}'),
            'tables': tables_status
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue/<venue_id>/upload-logo', methods=['POST'])
@require_login
def upload_venue_logo(venue_id):
    """Upload logo for a venue"""
    try:
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        if 'logo' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['logo']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Save logo file
        import uuid
        file_ext = os.path.splitext(file.filename)[1] or '.png'
        logo_filename = f"{venue_id}_{uuid.uuid4().hex[:8]}{file_ext}"
        logo_path = os.path.join(VENUE_LOGOS_DIR, logo_filename)
        file.save(logo_path)
        
        # Update venue metadata
        venue_metadata[venue_id]['logo_path'] = logo_filename
        
        return jsonify({
            'success': True,
            'logo_url': f'/venue-logos/{logo_filename}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue-logos/<filename>')
def serve_venue_logo(filename):
    """Serve venue logo files"""
    try:
        return send_from_directory(VENUE_LOGOS_DIR, filename)
    except:
        return jsonify({'error': 'Logo not found'}), 404


@app.route('/venue/<venue_id>/generate-qr-background', methods=['POST'])
@require_login
def generate_qr_background(venue_id):
    """Generate background image for QR code using DALL-E"""
    try:
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        if not OPENAI_API_KEY:
            return jsonify({'success': False, 'error': 'OpenAI API key not configured'}), 500
        
        bg_filename, error = _generate_background_for_venue(venue_id)
        if error:
            return jsonify({'success': False, 'error': error}), 500
        
        return jsonify({
            'success': True,
            'background_url': f'/venue-qr-backgrounds/{bg_filename}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue-qr-backgrounds/<filename>')
def serve_qr_background(filename):
    """Serve QR code background images"""
    try:
        return send_from_directory(VENUE_QR_CODES_DIR, filename)
    except:
        return jsonify({'error': 'Background not found'}), 404


def _generate_background_for_venue(venue_id):
    """Helper function to generate background image for venue (called internally)"""
    try:
        venue_name = venue_metadata[venue_id].get('name', f'Venue {venue_id}')
        
        prompt = f"A professional, elegant background for a QR code for {venue_name}. The background should be square (1:1 ratio), modern, with subtle colors that complement a QR code overlay. Include subtle abstract patterns or textures that don't interfere with QR code scanning."
        
        headers = {
            'Authorization': f'Bearer {OPENAI_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': 'dall-e-3',
            'prompt': prompt,
            'n': 1,
            'size': '1024x1024',
            'quality': 'standard'
        }
        
        response = requests.post(
            'https://api.openai.com/v1/images/generations',
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code != 200:
            return None, f'DALL-E API error: {response.text}'
        
        result = response.json()
        image_url = result['data'][0]['url']
        
        img_response = requests.get(image_url, timeout=30)
        img_response.raise_for_status()
        
        import uuid
        bg_filename = f"{venue_id}_bg_{uuid.uuid4().hex[:8]}.png"
        bg_path = os.path.join(VENUE_QR_CODES_DIR, bg_filename)
        
        with open(bg_path, 'wb') as f:
            f.write(img_response.content)
        
        venue_metadata[venue_id]['qr_background'] = bg_filename
        save_data()  # Save updated venue metadata
        return bg_filename, None
    except Exception as e:
        return None, str(e)


@app.route('/venue/<venue_id>/generate-custom-qr', methods=['POST'])
@require_login
def generate_custom_qr(venue_id):
    """Generate custom QR code with AI-generated background for venue"""
    try:
        if venue_id not in venue_metadata:
            return jsonify({'success': False, 'error': 'Venue not found'}), 404
        
        data = request.get_json()
        qr_data = data.get('qr_data')  # URL or text for QR code
        
        if not qr_data:
            return jsonify({'success': False, 'error': 'QR data required'}), 400
        
        # Get or generate background
        bg_filename = venue_metadata[venue_id].get('qr_background')
        if not bg_filename:
            # Generate background first
            bg_filename, error = _generate_background_for_venue(venue_id)
            if error:
                return jsonify({'success': False, 'error': error}), 500
        
        bg_path = os.path.join(VENUE_QR_CODES_DIR, bg_filename)
        if not os.path.exists(bg_path):
            return jsonify({'success': False, 'error': 'Background not found'}), 404
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        # Create QR code image
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_img = qr_img.convert("RGBA")
        
        # Resize QR code to fit nicely on background (about 40% of background)
        bg_img = Image.open(bg_path).convert("RGBA")
        bg_size = bg_img.size[0]  # Assuming square
        qr_size = int(bg_size * 0.4)
        qr_img = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
        
        # Create a white padding around QR code for better contrast
        padding = 20
        qr_with_padding = Image.new('RGBA', (qr_size + padding * 2, qr_size + padding * 2), (255, 255, 255, 220))
        qr_with_padding.paste(qr_img, (padding, padding), qr_img)
        
        # Center QR code on background
        x = (bg_size - qr_size - padding * 2) // 2
        y = (bg_size - qr_size - padding * 2) // 2
        
        # Optionally add logo in center of QR code if exists
        logo_path = venue_metadata[venue_id].get('logo_path')
        if logo_path:
            try:
                logo_full_path = os.path.join(VENUE_LOGOS_DIR, logo_path)
                if os.path.exists(logo_full_path):
                    logo_img = Image.open(logo_full_path).convert("RGBA")
                    logo_size = int(qr_size * 0.25)  # Logo is 25% of QR code size
                    logo_img = logo_img.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
                    
                    # Create white circle background for logo
                    logo_bg_size = logo_size + 10
                    logo_bg = Image.new('RGBA', (logo_bg_size, logo_bg_size), (255, 255, 255, 255))
                    mask = Image.new('L', (logo_bg_size, logo_bg_size), 0)
                    draw = ImageDraw.Draw(mask)
                    draw.ellipse([0, 0, logo_bg_size, logo_bg_size], fill=255)
                    logo_bg.putalpha(mask)
                    
                    # Paste logo on white circle
                    logo_offset = (logo_bg_size - logo_size) // 2
                    logo_bg.paste(logo_img, (logo_offset, logo_offset), logo_img)
                    
                    # Center logo on QR code
                    logo_x = x + (qr_size + padding * 2 - logo_bg_size) // 2
                    logo_y = y + (qr_size + padding * 2 - logo_bg_size) // 2
                    bg_img.paste(logo_bg, (logo_x, logo_y), logo_bg)
            except Exception as e:
                print(f"Error adding logo to QR code: {e}")
        
        # Paste QR code on background
        bg_img.paste(qr_with_padding, (x, y), qr_with_padding)
        
        # Save final QR code
        import uuid
        final_filename = f"{venue_id}_qr_{uuid.uuid4().hex[:8]}.png"
        final_path = os.path.join(VENUE_QR_CODES_DIR, final_filename)
        bg_img.save(final_path, 'PNG')
        
        return jsonify({
            'success': True,
            'qr_code_url': f'/venue-qr-codes/{final_filename}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/venue-qr-codes/<filename>')
def serve_custom_qr(filename):
    """Serve custom QR code images"""
    try:
        return send_from_directory(VENUE_QR_CODES_DIR, filename)
    except:
        return jsonify({'error': 'QR code not found'}), 404


@app.route('/demo/request', methods=['POST'])
def demo_request():
    """Handle demo request submissions"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        venue = data.get('venue', '').strip()
        
        if not name or not email:
            return jsonify({'success': False, 'error': 'Name and email are required'}), 400
        
        # Save demo request to file (you can later integrate with email service)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"demo_request_{timestamp}.txt"
        filepath = os.path.join(MESSAGES_DIR, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Demo Request\n")
            f.write(f"Name: {name}\n")
            f.write(f"Email: {email}\n")
            f.write(f"Venue: {venue or 'Not provided'}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        
        print(f"Demo request received: {name} ({email}) - Venue: {venue}")
        
        return jsonify({
            'success': True,
            'message': 'Demo request submitted successfully'
        })
    except Exception as e:
        print(f"Error processing demo request: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/debug/data')
@require_login
def debug_data():
    """Debug endpoint to check data persistence"""
    load_data()  # Reload from disk
    return jsonify({
        'data_dir': DATA_DIR,
        'data_dir_exists': os.path.exists(DATA_DIR),
        'venue_metadata_file': VENUE_METADATA_FILE,
        'venue_metadata_file_exists': os.path.exists(VENUE_METADATA_FILE),
        'venue_owners_file': VENUE_OWNERS_FILE,
        'venue_owners_file_exists': os.path.exists(VENUE_OWNERS_FILE),
        'in_memory_venues': len(venue_metadata),
        'in_memory_venue_ids': list(venue_metadata.keys()),
        'in_memory_owners': len(venue_owners),
        'in_memory_owner_emails': list(venue_owners.keys()),
        'current_user': session.get('user_id'),
        'user_venues': venue_owners.get(session.get('user_id'), []),
        'persistent_data_dir': PERSISTENT_DATA_DIR,
        'data_base_dir': DATA_BASE_DIR,
    })

if __name__ == '__main__':
    # Use PORT from environment variable (Railway/Heroku) or default to 8000
    port = int(os.environ.get('PORT', 8000))
    # Disable debug mode in production
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    if debug:
        local_ip = get_local_ip()
        print(f"\n{'='*60}")
        print("Server starting...")
        print(f"Local access: http://127.0.0.1:{port}")
        print(f"Network access: http://{local_ip}:{port}")
        print(f"QR Code: http://{local_ip}:{port}/qr")
        print(f"{'='*60}\n")
    
    app.run(debug=debug, host='0.0.0.0', port=port)
