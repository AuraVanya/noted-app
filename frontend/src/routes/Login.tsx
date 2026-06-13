import { Brand } from "@/components/BrandMark";
import { GoogleIcon } from "@/components/GoogleIcon";
import { Button } from "@/components/ui/button";

export const Login = () => {
  return (
    <div
      className="grid min-h-screen place-items-center p-6"
      style={{
        background:
          "radial-gradient(120% 120% at 80% -10%, #EFEFFB 0%, hsl(var(--background)) 46%)",
      }}
    >
      <div className="w-full max-w-[380px] rounded-[18px] border border-border bg-card px-[34px] pb-[30px] pt-[38px] shadow-md">
        <div className="mb-[30px]">
          <Brand />
        </div>

        <h1 className="mb-1.5 text-[22px] font-semibold leading-[1.25] tracking-[-0.025em] text-ink">
          Every meeting, one source of truth.
        </h1>
        <p className="mb-[26px] text-[13.5px] text-muted-foreground">
          Turn your team's meeting minutes into shared context — searchable,
          linked to Confluence and Jira, and ready for Claude.
        </p>

        <form
          onSubmit={(e) => {
            // Email is decorative for now — Google sign-in is the only real path.
            e.preventDefault();
            window.location.href = "/api/auth/google/login";
          }}
        >
          <div className="mb-3">
            <label
              htmlFor="email"
              className="mb-1.5 block text-xs font-medium text-ink-2"
            >
              Work email
            </label>
            <input
              id="email"
              type="email"
              placeholder="you@company.com"
              autoComplete="email"
              className="w-full rounded-md border border-border-strong bg-card px-[13px] py-[11px] text-sm transition-colors focus:border-primary focus:outline-none focus:ring-[3px] focus:ring-accent-tint"
            />
          </div>
          <Button type="submit" className="w-full">
            Continue
          </Button>
        </form>

        <div className="my-[18px] flex items-center gap-3 text-xs text-muted-foreground-2 before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border">
          or
        </div>

        <Button
          variant="outline"
          className="w-full"
          onClick={() => {
            window.location.href = "/api/auth/google/login";
          }}
        >
          <GoogleIcon />
          Continue with Google
        </Button>

        <p className="mt-6 text-center text-[11.5px] leading-[1.6] text-muted-foreground-2">
          SSO is handled through your Google Workspace account.
          <br />
          Drive and Calendar access are granted in the same consent flow.
        </p>
      </div>
    </div>
  );
};
