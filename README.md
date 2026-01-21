# whatsthat

A Flask-based music request system for venues using Suno AI for music generation.

## Features

- Venue management system
- User authentication (admin and venue owners)
- Music generation via Suno API
- QR code generation for song requests
- Table-based request system
- Genre control for admins
- Real-time queue management

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set environment variables:
- `SUNO_API_KEY` - Your Suno API key
- `OPENAI_API_KEY` - Your OpenAI API key (for DALL-E if needed)
- `GEMINI_API_KEY` - Your Google Gemini Studio API key (for future AI features)
- `GOOGLE_PLACES_API_KEY` - Your Google Places API key (optional, for demo venue profiling)
- `SECRET_KEY` - Flask secret key for sessions

3. Run the application:
```bash
python app.py
```

## Deployment to Railway

1. Push this repository to GitHub
2. Connect your GitHub repository to Railway
3. Set the following environment variables in Railway:
   - `SUNO_API_KEY`
   - `OPENAI_API_KEY`
   - `GEMINI_API_KEY` (for future AI features)
   - `GOOGLE_PLACES_API_KEY` (optional, for demo venue profiling)
   - `SECRET_KEY` (generate a secure random string)
4. Railway will automatically deploy and assign a domain

## Default Admin Credentials

- Email: `admin@whatsthat.com`
- Password: `admin123` (change this in production!)
