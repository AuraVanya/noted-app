import { cn } from "@/lib/utils";

/**
 * Noted brand mark — matches docs/noted-logo.html. A rounded purple square
 * (#4B45C6) with four horizontal "note" lines of varying width and opacity.
 */

interface BrandMarkProps {
  size?: number;
  className?: string;
}

export const BrandMark = ({ size = 30, className }: BrandMarkProps) => (
  <svg
    viewBox="0 0 36 36"
    fill="none"
    width={size}
    height={size}
    className={cn("shrink-0", className)}
    aria-hidden
  >
    <rect width="36" height="36" rx="8" fill="#4B45C6" />
    <rect
      x="7"
      y="8"
      width="14"
      height="2.8"
      rx="1.4"
      fill="white"
      opacity="0.5"
    />
    <rect x="7" y="14.5" width="22" height="2.8" rx="1.4" fill="white" />
    <rect x="7" y="21" width="22" height="2.8" rx="1.4" fill="white" />
    <rect
      x="7"
      y="27.5"
      width="13"
      height="2.8"
      rx="1.4"
      fill="white"
      opacity="0.35"
    />
  </svg>
);

interface BrandProps {
  size?: "sm" | "md";
}

export const Brand = ({ size = "md" }: BrandProps) => (
  <div className="flex items-center gap-[10px]">
    <BrandMark size={size === "sm" ? 22 : 30} />
    <span
      className={cn(
        "font-semibold tracking-tight text-ink",
        size === "sm" ? "text-[15.5px]" : "text-[18px]",
      )}
    >
      noted<span className="text-primary">.</span>
    </span>
  </div>
);
