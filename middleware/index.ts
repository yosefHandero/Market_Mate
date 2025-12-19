import { NextRequest, NextResponse } from "next/server";
import { getSessionCookie } from "better-auth/cookies";
import { cookies } from "next/headers";

export async function middleware(request: NextRequest) {
    // Check for demo mode cookie first
    const cookieStore = await cookies();
    const demoMode = cookieStore.get('demo-mode');
    
    if (demoMode?.value === 'true') {
        return NextResponse.next();
    }

    // Check for Better Auth session
    const sessionCookie = getSessionCookie(request);

    if (!sessionCookie) {
        // Redirect to sign-in instead of "/" to avoid redirect loop
        return NextResponse.redirect(new URL("/sign-in", request.url));
    }

    return NextResponse.next();
}

export const config = {
    matcher: [
        '/((?!api|_next/static|_next/image|logo.png|sign-in|sign-up|assets).*)',
    ],
};
