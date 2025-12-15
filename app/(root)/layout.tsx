import Header from "@/components/Header";
import {getCurrentUser} from "@/lib/auth/session";
import {redirect} from "next/navigation";

const Layout = async ({ children }: { children : React.ReactNode }) => {
    const currentUser = await getCurrentUser();

    if(!currentUser) redirect('/sign-in');

    const user = {
        id: currentUser.id,
        name: currentUser.name || 'User',
        email: currentUser.email || '',
    }

    return (
        <main className="min-h-screen text-gray-400">
            <Header user={user} />

            <div className="container py-10">
                {children}
            </div>
        </main>
    )
}
export default Layout
