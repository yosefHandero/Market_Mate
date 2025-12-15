'use server';

import {getAuth} from "@/lib/better-auth/auth";
import {inngest} from "@/lib/inngest/client";
import {headers, cookies} from "next/headers";

export const signUpWithEmail = async ({ email, password, fullName, country, investmentGoals, riskTolerance, preferredIndustry }: SignUpFormData) => {
    try {
        const auth = await getAuth();
        const response = await auth.api.signUpEmail({ 
            body: { email, password, name: fullName },
            headers: await headers()
        })

        if(!response) {
            console.error('Sign up failed: No response from auth.api.signUpEmail')
            return { success: false, error: 'No response from authentication server' }
        }

        // Check if response has an error
        if('error' in response && response.error) {
            console.error('Sign up failed:', response.error)
            return { success: false, error: response.error.message || 'Sign up failed' }
        }

        if(response) {
            try {
                await inngest.send({
                    name: 'app/user.created',
                    data: { email, name: fullName, country, investmentGoals, riskTolerance, preferredIndustry }
                })
            } catch (inngestError) {
                // Don't fail sign-up if Inngest fails
                console.warn('Failed to send Inngest event:', inngestError)
            }
        }

        return { success: true, data: response }
    } catch (e) {
        console.error('Sign up failed:', e)
        console.error('Error details:', {
            message: e instanceof Error ? e.message : 'Unknown error',
            stack: e instanceof Error ? e.stack : undefined,
            name: e instanceof Error ? e.name : typeof e
        })
        const errorMessage = e instanceof Error ? e.message : 'Sign up failed'
        return { success: false, error: errorMessage }
    }
}

export const signInWithEmail = async ({ email, password }: SignInFormData) => {
    try {
        const auth = await getAuth();
        const response = await auth.api.signInEmail({ 
            body: { email, password },
            headers: await headers()
        })

        return { success: true, data: response }
    } catch (e) {
        console.log('Sign in failed', e)
        const errorMessage = e instanceof Error ? e.message : 'Sign in failed'
        return { success: false, error: errorMessage }
    }
}

export const signOut = async () => {
    try {
        // Clear demo mode cookie if it exists
        const cookieStore = await cookies();
        cookieStore.delete('demo-mode');
        
        // Also sign out from Better Auth if there's a session
        try {
            const auth = await getAuth();
            await auth.api.signOut({ headers: await headers() });
        } catch (authError) {
            // Ignore auth errors if user is in demo mode
            console.log('Auth sign out skipped (may be demo user)');
        }
        
        return { success: true };
    } catch (e) {
        console.log('Sign out failed', e)
        return { success: false, error: 'Sign out failed' }
    }
}

export const exitDemo = async () => {
    try {
        // Clear demo mode cookie
        const cookieStore = await cookies();
        cookieStore.delete('demo-mode');
        
        return { success: true };
    } catch (e) {
        console.log('Exit demo failed', e)
        return { success: false, error: 'Exit demo failed' }
    }
}

export const signInAsDemo = async () => {
    try {
        // Set demo mode cookie directly - bypasses Better Auth
        const cookieStore = await cookies();
        cookieStore.set('demo-mode', 'true', {
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'lax',
            maxAge: 60 * 60 * 24 * 7, // 7 days
        });

        return { 
            success: true, 
            data: {
                user: {
                    id: 'demo-user-yosef',
                    name: 'Yosef',
                    email: 'demo@marketmate.com'
                }
            }
        };
    } catch (e) {
        console.error('Demo sign in failed:', e);
        const errorMessage = e instanceof Error ? e.message : 'Demo sign in failed';
        return { success: false, error: errorMessage };
    }
}
