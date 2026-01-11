# Quick Deployment Guide

## 🚀 Deploy to GitHub & Railway

### Step 1: Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `whatsthat`
3. Make it Public or Private
4. **DO NOT** check any initialization options
5. Click "Create repository"

### Step 2: Push to GitHub

Run these commands (replace YOUR_USERNAME with your GitHub username):

```bash
git remote add origin https://github.com/YOUR_USERNAME/whatsthat.git
git branch -M main
git push -u origin main
```

**If asked for credentials:**
- Username: Your GitHub username
- Password: Use a Personal Access Token (create at: https://github.com/settings/tokens)

### Step 3: Deploy to Railway

1. Go to https://railway.app and sign in
2. Click "New Project" → "Deploy from GitHub repo"
3. Authorize Railway → Select your `whatsthat` repository
4. Railway will auto-detect Python and start building

### Step 4: Set Environment Variables

In Railway dashboard → Your Project → Variables, add:

```
SUNO_API_KEY = (your Suno API key)
OPENAI_API_KEY = (your OpenAI API key)
SECRET_KEY = (generate with: python -c "import secrets; print(secrets.token_hex(32))")
```

### Step 5: Get Your Live URL

Railway will assign a domain like: `your-app.up.railway.app`

You can find it in Railway dashboard → Settings → Domains

### ✅ Done!

Your app is now live! Visit your Railway domain to test it.

