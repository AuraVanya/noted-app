import { NavLink } from "react-router-dom";
import {
  Calendar as CalendarIcon,
  FileText,
  Home as HomeIcon,
  Lightbulb,
  Ticket,
} from "lucide-react";

import { Brand } from "@/components/BrandMark";
import type { Me } from "@/hooks/useMe";
import { cn } from "@/lib/utils";

interface NavEntry {
  to: string;
  label: string;
  end?: boolean;
  icon: typeof HomeIcon;
}

const NAV_ITEMS: NavEntry[] = [
  { to: "/", label: "Home", end: true, icon: HomeIcon },
  { to: "/calendar", label: "Calendar", icon: CalendarIcon },
  { to: "/minutes", label: "Minutes", icon: FileText },
  { to: "/tickets", label: "Tickets", icon: Ticket },
  { to: "/projects", label: "Projects", icon: Lightbulb },
];

interface SidebarProps {
  user: Me;
}

export const Sidebar = ({ user }: SidebarProps) => {
  return (
    <aside className="sticky top-0 flex h-screen w-[236px] flex-none flex-col gap-1 border-r border-border bg-card px-[14px] py-[18px]">
      <div className="px-2 pb-4 pt-1.5">
        <Brand size="sm" />
      </div>

      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "group flex w-full items-center gap-[11px] rounded-md px-2.5 py-2.5 text-[13.5px] font-medium text-ink-2 transition-colors",
                "hover:bg-surface-2",
                isActive && "bg-accent-tint font-semibold text-primary",
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon
                  size={18}
                  className={cn(
                    "flex-none text-muted-foreground",
                    isActive && "text-primary",
                  )}
                  strokeWidth={1.8}
                />
                <span>{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="flex-1" />

      <NavLink
        to="/profile"
        className={({ isActive }) =>
          cn(
            "flex w-full items-center gap-2.5 rounded-md border border-border bg-surface-2 px-2 py-2.5 text-left transition-colors hover:bg-[hsl(240_8%_95%)]",
            isActive && "border-border-strong",
          )
        }
      >
        <span className="grid h-[30px] w-[30px] flex-none place-items-center rounded-full bg-gradient-to-br from-[#6E68E0] to-primary text-[12px] font-semibold text-primary-foreground">
          {user.avatarInitials}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] font-semibold leading-[1.2] text-ink">
            {user.displayName}
          </span>
          <span className="block truncate text-[11px] text-muted-foreground">
            {user.email}
          </span>
        </span>
      </NavLink>
    </aside>
  );
};
