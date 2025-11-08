import { headers } from "next/headers";

import { auth } from "@/lib/better-auth/auth";

export type CurrentUser = {
  id: string;
  email?: string | null;
  name?: string | null;
};

async function getSessionFromHeaders(headersInit: HeadersInit) {
  try {
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

export async function getCurrentUserFromHeaders(
  headersInit: HeadersInit
): Promise<CurrentUser | null> {
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
