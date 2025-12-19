import { getAuth } from "@/lib/better-auth/auth";
import { toNextJsHandler } from "better-auth/next-js";
import type { NextRequest } from "next/server";

// Lazy initialization - handlers will await auth on first request
type AuthHandlers = ReturnType<typeof toNextJsHandler>;
let handlers: AuthHandlers | null = null;

async function getHandlers(): Promise<AuthHandlers> {
    if(!handlers) {
        const auth = await getAuth();
        handlers = toNextJsHandler(auth);
    }
    return handlers;
}

export async function GET(request: NextRequest) {
    const handlers = await getHandlers();
    return handlers.GET(request);
}

export async function POST(request: NextRequest) {
    const handlers = await getHandlers();
    return handlers.POST(request);
}

