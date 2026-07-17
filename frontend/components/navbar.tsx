"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bookmark, LayoutDashboard, Search, Settings, Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/theme-toggle";

const links = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/search/new", label: "New Search", icon: Search },
  { href: "/saved", label: "Saved", icon: Bookmark },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Navbar() {
  const pathname = usePathname();

  return (
    <header className="fixed inset-x-0 top-4 z-40 px-4">
      <div className="glass mx-auto flex h-14 max-w-6xl items-center justify-between rounded-2xl pl-3 pr-2">
        <Link href="/" className="group flex items-center gap-2.5 font-semibold">
          <span className="bg-gradient-brand flex size-9 items-center justify-center rounded-xl text-white shadow-glow">
            <Sparkles className="size-[18px]" />
          </span>
          <span className="hidden font-heading text-[15px] sm:inline">
            Talent<span className="text-gradient">Finder</span>
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {links.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-colors duration-200",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                <span className="hidden md:inline">{label}</span>
              </Link>
            );
          })}
          <div className="ml-1 border-l border-border pl-1">
            <ThemeToggle />
          </div>
        </nav>
      </div>
    </header>
  );
}
