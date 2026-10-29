"use client";

import { ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  Boxes,
  ChevronLeft,
  LayoutDashboard,
  Library,
  LogOut,
  Package,
  Settings,
  ShieldCheck,
  Terminal,
  Users,
  Wrench,
} from "lucide-react";
import { useSession, useSSE } from "@/lib/hooks";
import { post } from "@/lib/api";
import { Avatar } from "./ui";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/employees", label: "Employees", icon: Users },
  { href: "/tasks", label: "Tasks", icon: Terminal },
  { href: "/teams", label: "Teams", icon: Boxes },
  { href: "/tools", label: "Tools & Skills", icon: Wrench },
  { href: "/library", label: "Capability Library", icon: Library },
  { href: "/artifacts", label: "Artifacts", icon: Package },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, checking } = useSession(true);
  const [open, setOpen] = useState(false);
  const [live, setLive] = useState(false);

  useSSE(["activity"], () => setLive(true));

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted">
        Checking session…
      </div>
    );
  }

  const signOut = async () => {
    try {
      await post("/api/auth/logout");
    } finally {
      router.replace("/auth");
    }
  };

  return (
    <div className="app-grid">
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-line bg-surface transition-transform lg:static lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-14 items-center justify-between border-b border-line px-4">
          <Link href="/dashboard" className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-graphite text-[13px] font-bold text-white">
              B
            </span>
            <span className="text-[15px] font-semibold tracking-tight">Bozii</span>
          </Link>
          <button className="lg:hidden" onClick={() => setOpen(false)} aria-label="Close navigation">
            <ChevronLeft size={16} className="text-muted" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {NAV.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`mb-0.5 flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                  active
                    ? "bg-surface-2 font-medium text-ink"
                    : "text-muted hover:bg-surface-2 hover:text-ink"
                }`}
              >
                <Icon size={16} className={active ? "text-accent" : ""} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-line p-3">
          <div className="flex items-center gap-2.5">
            <Avatar name={user?.name || user?.email || "?"} size={30} color="#18181b" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">{user?.name || "Signed in"}</p>
              <p className="truncate text-[11px] text-muted">{user?.email}</p>
            </div>
            <button
              onClick={signOut}
              title="Sign out"
              aria-label="Sign out"
              className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-ink"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>

      {open ? (
        <div className="fixed inset-0 z-30 bg-graphite/30 lg:hidden" onClick={() => setOpen(false)} />
      ) : null}

      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-canvas/90 px-4 backdrop-blur lg:px-6">
          <button
            className="lg:hidden"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
            aria-expanded={open}
          >
            <span className="block h-0.5 w-5 bg-ink" />
            <span className="mt-1 block h-0.5 w-5 bg-ink" />
            <span className="mt-1 block h-0.5 w-5 bg-ink" />
          </button>
          <div className="hidden items-center gap-2 text-xs text-muted sm:flex">
            <span className="flex items-center gap-1.5">
              <span className={live ? "pulse-dot" : "h-1.5 w-1.5 rounded-full bg-line-strong"} />
              {live ? "Live updates connected" : "Live updates connecting…"}
            </span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Link
              href="/settings#providers"
              className="hidden items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs text-ink-2 hover:bg-surface-2 sm:flex"
            >
              <ShieldCheck size={13} className="text-accent" />
              Sandbox status
            </Link>
          </div>
        </header>
        <main className="px-4 py-6 lg:px-6">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {action ? <div className="flex items-center gap-2">{action}</div> : null}
    </div>
  );
}
