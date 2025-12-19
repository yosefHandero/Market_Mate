import Header from "@/components/Header";
import DemoTimer from "@/components/DemoTimer";
import { getCurrentUser, isDemoMode } from "@/lib/auth/session";
import { redirect } from "next/navigation";

const Layout = async ({ children }: { children: React.ReactNode }) => {
  const currentUser = await getCurrentUser();

  if (!currentUser) {
    redirect("/sign-in");
    return null; // TypeScript guard - redirect throws but helps with type checking
  }

  const user = {
    id: currentUser.id,
    name: currentUser.name || "User",
    email: currentUser.email || "",
  };

  const demoMode = await isDemoMode();

  return (
    <main className="min-h-screen text-gray-400">
      <DemoTimer isDemoMode={demoMode} />
      <Header user={user} />

      <div className="container py-10">{children}</div>
    </main>
  );
};
export default Layout;
