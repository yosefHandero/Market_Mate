import dotenv from 'dotenv';
import mongoose from 'mongoose';

// Load .env.local file
dotenv.config({ path: '.env.local' });

const MONGODB_URI = process.env.MONGODB_URI;

if (!MONGODB_URI) {
  console.error('ERROR: MONGODB_URI must be set in .env.local');
  process.exit(1);
}

async function keepAlive() {
  try {
    const startedAt = Date.now();
    await mongoose.connect(MONGODB_URI, { bufferCommands: false });
    const elapsed = Date.now() - startedAt;

    const dbName = mongoose.connection?.name || '(unknown)';
    const host = mongoose.connection?.host || '(unknown)';

    console.log(`✅ [${new Date().toLocaleTimeString()}] Keepalive ping successful [db="${dbName}", host="${host}", time=${elapsed}ms]`);
    await mongoose.disconnect();
    process.exit(0);
  } catch (error) {
    console.error(`❌ [${new Date().toLocaleTimeString()}] Keepalive failed:`, error.message);
    try {
      await mongoose.disconnect();
    } catch {}
    process.exit(1);
  }
}

keepAlive();

