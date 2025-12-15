import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

export async function GET() {
  const cookieStore = await cookies();
  
  // Set demo mode cookie
  cookieStore.set('demo-mode', 'true', {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 7, // 7 days
  });

  return NextResponse.json({ 
    success: true, 
    message: 'Demo mode activated',
    user: {
      id: 'demo-user-yosef',
      name: 'Yosef',
      email: 'demo@marketmate.com'
    }
  });
}

