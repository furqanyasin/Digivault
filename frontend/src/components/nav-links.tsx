"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Globe, Bell, Key, Users, LayoutDashboard, Building2, Settings,
  ClipboardList, FileText, CalendarClock, UserCircle, Flame, ShieldCheck,
  type LucideIcon,
} from "lucide-react";

// Icons are React components and cannot cross the RSC boundary as props,
// so the server layout passes string keys mapped here.
const ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutDashboard,
  clients: Building2,
  websites: Globe,
  renewals: CalendarClock,
  alerts: Bell,
  reports: FileText,
  credentials: Key,
  team: Users,
  logs: ClipboardList,
  account: UserCircle,
  settings: Settings,
  heatmap: Flame,
  platform: ShieldCheck,
};

export interface NavLinkItem {
  href: string;
  label: string;
  icon: string;
}

export function NavLinks({ items }: { items: NavLinkItem[] }) {
  const pathname = usePathname();

  return (
    <nav className="flex-1 px-3 py-4 space-y-1">
      {items.map(({ href, label, icon }) => {
        const Icon = ICONS[icon] ?? Globe;
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            /* Active is a solid fill, not a 10% tint. A tinted pill and a hover
               pill are the same weight at a glance, so "where am I" and "what
               is under the cursor" competed; only one of them should read as
               a state. */
            className={
              active
                ? "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold bg-primary text-primary-foreground shadow-sm transition-colors"
                : "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
