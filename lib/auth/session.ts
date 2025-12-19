import { headers, cookies } from "next/headers";

import { getAuth } from "@/lib/better-auth/auth";

export type CurrentUser = {
  id: string;
  email?: string | null;
  name?: string | null;
};

// Demo user data
const DEMO_USER: CurrentUser = {
  id: 'demo-user-yosef',
  email: 'demo@marketmate.com',
  name: 'Yosef',
};

async function getSessionFromHeaders(headersInit: HeadersInit) {
  try {
    const auth = await getAuth();
    return await auth.api.getSession({ headers: headersInit });
  } catch (error) {
    console.error("Failed to retrieve session", error);
    return null;
  }
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  const headersList = await headers();
  return getCurrentUserFromHeaders(headersList);
}

export async function isDemoMode(): Promise<boolean> {
  const cookieStore = await cookies();
  const demoMode = cookieStore.get('demo-mode');
  return demoMode?.value === 'true';
}

export async function getCurrentUserFromHeaders(
  headersInit: HeadersInit
): Promise<CurrentUser | null> {
  // Check for demo mode first
  const cookieStore = await cookies();
  const demoMode = cookieStore.get('demo-mode');
  
  if (demoMode?.value === 'true') {
    return DEMO_USER;
  }

  // Otherwise, check Better Auth session
  const session = await getSessionFromHeaders(headersInit);

  if (!session?.user?.id) {
    return null;
  }

  return {
    id: session.user.id,
    email: session.user.email ?? null,
    name: session.user.name ?? null,
  };
}
