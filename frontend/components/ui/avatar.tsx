"use client";

import * as React from "react";

import { cn, initials } from "@/lib/utils";

interface AvatarProps {
  src?: string | null;
  name: string;
  className?: string;
}

export function Avatar({ src, name, className }: AvatarProps) {
  const [errored, setErrored] = React.useState(false);
  const showImage = src && !errored;

  return (
    <div
      className={cn(
        "relative flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-full bg-secondary text-sm font-semibold text-secondary-foreground",
        className,
      )}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={name}
          className="size-full object-cover"
          onError={() => setErrored(true)}
        />
      ) : (
        <span>{initials(name)}</span>
      )}
    </div>
  );
}
