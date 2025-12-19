import { betterAuth } from "better-auth";
import { mongodbAdapter} from "better-auth/adapters/mongodb";
import { connectToDatabase} from "@/database/mongoose";
import { nextCookies} from "better-auth/next-js";

let authInstance: ReturnType<typeof betterAuth> | null = null;
let authPromise: Promise<ReturnType<typeof betterAuth>> | null = null;

export const getAuth = async () => {
    if(authInstance) return authInstance;

    if(authPromise) return authPromise;

    authPromise = (async () => {
        const mongoose = await connectToDatabase();
        const db = mongoose.connection.db;

        if(!db) throw new Error('MongoDB connection not found');

        if (!process.env.BETTER_AUTH_SECRET) {
            throw new Error('BETTER_AUTH_SECRET must be set in environment variables');
        }

        authInstance = betterAuth({
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            database: mongodbAdapter(db as any),
            secret: process.env.BETTER_AUTH_SECRET,
            baseURL: process.env.BETTER_AUTH_URL || 'http://localhost:3000',
            emailAndPassword: {
                enabled: true,
                disableSignUp: false,
                requireEmailVerification: false,
                minPasswordLength: 8,
                maxPasswordLength: 128,
                autoSignIn: true,
            },
            plugins: [nextCookies()],
        });

        return authInstance;
    })();

    return authPromise;
}

// Lazy getter for auth - use getAuth() in async contexts, or await this
export const getAuthSync = () => {
    if(!authInstance) {
        throw new Error('Auth not initialized. Use getAuth() in async context first.');
    }
    return authInstance;
}
