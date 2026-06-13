import { Outlet } from "react-router-dom";

import { Sidebar } from "@/components/Sidebar";
import type { Me } from "@/hooks/useMe";

interface AppShellProps {
  user: Me;
}

export const AppShell = ({ user }: AppShellProps) => (
  <div className="grid min-h-screen grid-cols-[236px_1fr]">
    <Sidebar user={user} />
    <main className="overflow-auto px-10 pb-16 pt-[34px]">
      <div className="mx-auto max-w-[1180px]">
        <Outlet />
      </div>
    </main>
  </div>
);
