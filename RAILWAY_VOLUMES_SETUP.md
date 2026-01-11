# Railway Volumes Setup - Easiest Solution for Persistent Storage

## What This Does
Railway Volumes provide persistent file storage that survives container restarts. This is the **easiest solution** - no database needed, minimal code changes.

## Step 1: Create Volume in Railway

1. Go to your Railway project dashboard
2. Click on your web service (the one running your Flask app)
3. Click the **"Settings"** tab
4. Scroll down to **"Volumes"** section
5. Click **"Add Volume"**
6. Name it: `persistent-data`
7. Mount Path: `/data`
8. Click **"Create"**

## Step 2: Update Environment Variables

In your Railway service settings:
1. Go to **"Variables"** tab
2. Add a new variable:
   - Name: `PERSISTENT_DATA_DIR`
   - Value: `/data`
3. Save

## Step 3: Code Updates (Already Done)

The code has been updated to:
- Use `/data` directory if `PERSISTENT_DATA_DIR` env var is set
- Store all JSON data files in the persistent volume
- Store all audio files in the persistent volume
- This means venues AND songs will persist forever (or until you delete them)

## What Gets Stored

- ✅ Venue metadata (venues persist across restarts)
- ✅ Venue queues
- ✅ Song audio files
- ✅ User data
- ✅ All other application data

## Benefits

- **Easiest solution** - just mount a volume, done
- **No code refactoring** - works with existing JSON file approach
- **Persistent** - data survives restarts, deployments, everything
- **24+ hours** - data persists indefinitely
- **Audio files persist** - songs stored on the volume

## Testing

After setup, create a venue and verify it persists after:
- Page refresh
- Container restart (Redeploy in Railway)
- New deployment

Your venues and songs will now be permanently stored! 🎉

