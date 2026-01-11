# Deployment Guide for Railway

## Step 1: Push to GitHub

1. Create a new repository on GitHub (don't initialize with README)

2. Add the remote and push:
```bash
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git branch -M main
git commit -m "Initial commit"
git push -u origin main
```

## Step 2: Deploy to Railway

1. Go to [Railway](https://railway.app) and sign in
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Authorize Railway to access your GitHub account
5. Select your repository
6. Railway will automatically detect it's a Python app and start building

## Step 3: Set Environment Variables

In Railway dashboard, go to your project → Variables tab and add:

- `SUNO_API_KEY` = (your Suno API key)
- `OPENAI_API_KEY` = (your OpenAI API key)
- `SECRET_KEY` = (generate a secure random string, e.g., use: `python -c "import secrets; print(secrets.token_hex(32))"`)
- `PORT` = (Railway sets this automatically, but you can leave it)

## Step 4: Get Your Domain

1. Railway will automatically assign a domain like `your-app.up.railway.app`
2. You can also add a custom domain in the Settings → Domains section

## Step 5: Verify Deployment

Once deployed, visit your Railway domain and test:
- Landing page loads
- Sign up works
- Login works
- Venue creation works

## Notes

- Railway automatically handles HTTPS
- The app will restart automatically on code pushes to GitHub
- Check logs in Railway dashboard if there are any issues

