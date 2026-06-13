import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useMe } from "@/hooks/useMe";
import { api } from "@/lib/api";

export const Profile = () => {
  const me = useMe();
  const queryClient = useQueryClient();

  const signOut = useMutation({
    mutationFn: () => api<void>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => {
      queryClient.setQueryData(["me"], null);
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  if (!me.data) return null;
  const { displayName, email, avatarInitials, connections } = me.data;

  return (
    <div>
      <div className="mb-6">
        <h2 className="mb-1 text-2xl font-bold tracking-tight text-ink">
          Profile
        </h2>
        <p className="text-sm text-muted-foreground">
          Your account and connected services.
        </p>
      </div>

      <Card className="mb-4">
        <CardContent className="flex items-center gap-4 p-6">
          <span className="grid h-12 w-12 flex-none place-items-center rounded-full bg-gradient-to-br from-[#6E68E0] to-primary text-base font-semibold text-primary-foreground">
            {avatarInitials}
          </span>
          <div className="min-w-0">
            <div className="text-base font-semibold text-ink">
              {displayName}
            </div>
            <div className="font-mono text-[12.5px] text-muted-foreground">
              {email}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardContent className="flex flex-col gap-3 p-6">
          <div className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted-foreground-2">
            Connected accounts
          </div>
          <div className="flex items-center justify-between border-t border-border pt-3">
            <span className="text-sm font-medium text-ink">Google</span>
            <span className="text-xs font-semibold text-[hsl(141_63%_33%)]">
              {connections.google ? "Connected" : "Not connected"}
            </span>
          </div>
          <div className="flex items-center justify-between border-t border-border pt-3">
            <span className="text-sm font-medium text-ink">Atlassian</span>
            <span className="text-xs font-semibold text-muted-foreground">
              {connections.atlassian ? "Connected" : "Connect in Phase 5"}
            </span>
          </div>
        </CardContent>
      </Card>

      <Button
        variant="outline"
        onClick={() => signOut.mutate()}
        disabled={signOut.isPending}
      >
        {signOut.isPending ? "Signing out…" : "Sign out"}
      </Button>
    </div>
  );
};
