import { NextResponse } from 'next/server';
import { connectToDatabase } from '@/database/mongoose';

export async function GET() {
  try {
    // Connect to database to keep it active
    await connectToDatabase();
    
    return NextResponse.json({ 
      success: true, 
      message: 'MongoDB keepalive ping successful',
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    console.error('Keepalive failed:', error);
    return NextResponse.json(
      { 
        success: false, 
        error: error instanceof Error ? error.message : 'Unknown error',
        timestamp: new Date().toISOString()
      },
      { status: 500 }
    );
  }
}

