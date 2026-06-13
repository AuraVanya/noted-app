import { cn } from "@/lib/utils";

interface BrandMarkProps {
  size?: number;
  className?: string;
}

export const BrandMark = ({ size = 30, className }: BrandMarkProps) => (
  <svg
    viewBox="0 0 32 32"
    fill="none"
    width={size}
    height={size}
    className={cn("shrink-0", className)}
    aria-hidden
  >
    <circle cx="6" cy="16" r="3.4" fill="#4B45C6" />
    <circle cx="16" cy="16" r="2.6" fill="#9A95EE" />
    <circle cx="26" cy="16" r="3.4" fill="#4B45C6" />
    <line x1="6" y1="16" x2="26" y2="16" stroke="#4B45C6" strokeWidth="2" />
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
      Noted
    </span>
  </div>
);
