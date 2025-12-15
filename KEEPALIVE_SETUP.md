# MongoDB Keepalive Setup with Online Cron Service

## API Endpoint Created

I've created an API endpoint at: `/api/keepalive`

This endpoint will:
- Connect to your MongoDB database
- Keep your cluster active
- Return a success/failure response

## Setup Instructions

### Step 1: Make Sure Your App is Running

Your Next.js app needs to be running (either in development or production) for the cron service to ping it.

**For Development:**
```bash
npm run dev
```

**For Production:**
```bash
npm run build
npm start
```

### Step 2: Get Your Public URL

You need a publicly accessible URL for the cron service to ping:

**Option A: Deploy to Vercel/Netlify (Recommended)**
- Deploy your app to Vercel (free) or Netlify
- Get your production URL (e.g., `https://your-app.vercel.app`)
- Use: `https://your-app.vercel.app/api/keepalive`

**Option B: Use a Tunneling Service (For Local Development)**
- Use **ngrok**: `ngrok http 3000`
- Or use **Cloudflare Tunnel**: `cloudflared tunnel --url http://localhost:3000`
- Get the public URL and use: `https://your-tunnel-url.ngrok.io/api/keepalive`

**Option C: Use Localhost (Only if cron service supports it)**
- Some services can ping localhost if you install their agent
- Use: `http://localhost:3000/api/keepalive`

### Step 3: Choose a Cron Service

Here are free options:

#### **UptimeRobot** (Recommended - Free Tier: 50 monitors)
1. Go to: https://uptimerobot.com
2. Sign up for free account
3. Click "Add New Monitor"
4. Monitor Type: **HTTP(s)**
5. Friendly Name: `MongoDB Keepalive`
6. URL: `https://your-app-url.com/api/keepalive`
7. Monitoring Interval: **5 minutes** (minimum)
8. Click "Create Monitor"

#### **Cron-job.org** (Free Tier Available)
1. Go to: https://cron-job.org
2. Sign up for free account
3. Click "Create cronjob"
4. Title: `MongoDB Keepalive`
5. Address: `https://your-app-url.com/api/keepalive`
6. Schedule: Every **30 minutes**
7. Click "Create"

#### **EasyCron** (Free Tier Available)
1. Go to: https://www.easycron.com
2. Sign up for free account
3. Create new cron job
4. URL: `https://your-app-url.com/api/keepalive`
5. Schedule: `*/30 * * * *` (every 30 minutes)
6. Save

### Step 4: Test the Endpoint

Before setting up the cron service, test your endpoint:

```bash
# If running locally
curl http://localhost:3000/api/keepalive

# Should return:
# {"success":true,"message":"MongoDB keepalive ping successful","timestamp":"..."}
```

### Step 5: Monitor

Check your cron service dashboard to see if the pings are successful. The endpoint will:
- ✅ Return `{"success": true}` if MongoDB connection works
- ❌ Return `{"success": false}` with error details if it fails

## Important Notes

1. **Your app must be running** for the cron service to work
2. **For production**, deploy to Vercel/Netlify (free) for 24/7 uptime
3. **For development**, use ngrok or keep your dev server running
4. **Ping every 30-50 minutes** to keep cluster active (MongoDB pauses after 1 hour)
5. **The endpoint is public** - consider adding basic auth if needed (optional)

## Optional: Add Basic Authentication

If you want to secure the endpoint, you can add a simple API key check:

```typescript
// In app/api/keepalive/route.ts
const KEEPALIVE_KEY = process.env.KEEPALIVE_API_KEY;

export async function GET(request: NextRequest) {
  const authHeader = request.headers.get('authorization');
  if (authHeader !== `Bearer ${KEEPALIVE_KEY}`) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  // ... rest of the code
}
```

Then set `KEEPALIVE_API_KEY` in your `.env.local` and configure the cron service to send it as a header.

