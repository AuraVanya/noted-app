import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAtlassianIdentity } from "@/hooks/useAtlassianIdentity";
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
          <AtlassianConnectionRow connected={connections.atlassian} />
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

const AtlassianConnectionRow = ({ connected }: { connected: boolean }) => {
  const queryClient = useQueryClient();
  const identity = useAtlassianIdentity(connected);
  const disconnect = useMutation({
    mutationFn: () =>
      api<void>("/api/auth/atlassian/disconnect", { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["me"] });
      queryClient.removeQueries({ queryKey: ["atlassian-identity"] });
    },
  });

  return (
    <div className="border-t border-border pt-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-ink">Atlassian</span>
        <div className="flex items-center gap-3">
          {connected ? (
            <>
              <span className="text-xs font-semibold text-[hsl(141_63%_33%)]">
                Connected
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => disconnect.mutate()}
                disabled={disconnect.isPending}
              >
                {disconnect.isPending ? "Disconnecting…" : "Disconnect"}
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              onClick={() => {
                window.location.href = "/api/auth/atlassian/login";
              }}
            >
              Connect Atlassian
            </Button>
          )}
        </div>
      </div>
      {connected && identity.data && (
        <div className="mt-2 flex items-center gap-2 text-[11.5px] text-muted-foreground">
          {identity.data.avatarUrl && (
            <img
              src={identity.data.avatarUrl}
              alt=""
              className="h-4 w-4 rounded-full"
            />
          )}
          <span>
            Connected as{" "}
            <strong className="font-semibold text-ink-2">
              {identity.data.displayName}
            </strong>
            {identity.data.email && (
              <>
                {" "}
                · <span className="font-mono">{identity.data.email}</span>
              </>
            )}
          </span>
        </div>
      )}
      {connected && identity.isError && (
        <p className="mt-2 text-[11.5px] text-destructive">
          Couldn't resolve Atlassian identity: {identity.error.message}
        </p>
      )}
    </div>
  );
};
