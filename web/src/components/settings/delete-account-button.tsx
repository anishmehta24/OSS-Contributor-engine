"use client";

import * as React from "react";
import { Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";

/**
 * Destructive, two-step confirmation:
 *   1. Click "Delete my account" → opens dialog
 *   2. Type "DELETE" into the field → Confirm enables
 *   3. Confirm → DELETE /api/users/me, then POST /api/auth/logout via form
 */
export function DeleteAccountButton({ login }: { login: string }) {
  const [open, setOpen] = React.useState(false);
  const [confirmation, setConfirmation] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const canDelete = confirmation === "DELETE";

  async function confirm() {
    if (!canDelete || pending) return;
    setPending(true);
    try {
      const del = await fetch("/api/users/me", {
        method: "DELETE",
        cache: "no-store",
      });
      if (!del.ok && del.status !== 204) {
        throw new Error(`HTTP ${del.status}`);
      }
      toast.success("Account deleted. Signing you out.");
      // POST to our own logout endpoint to clear the Next.js cookie too.
      // The form auto-redirects to "/" on success.
      const form = document.createElement("form");
      form.method = "POST";
      form.action = "/api/auth/logout";
      document.body.appendChild(form);
      form.submit();
    } catch (err) {
      setPending(false);
      toast.error("Account deletion failed.", {
        description: err instanceof Error ? err.message : "",
      });
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setConfirmation("");
      }}
    >
      <DialogTrigger
        render={
          <Button variant="destructive" size="sm">
            <Trash2 className="mr-2 size-3.5" />
            Delete my account
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete your account?</DialogTitle>
          <DialogDescription>
            This permanently removes your profile, investigations, pitches,
            and the encrypted OAuth token we hold for you. You can re-create
            the account by signing in again, but the historical data is gone.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="confirm-delete">
            Type <span className="font-mono font-semibold">DELETE</span> to
            confirm
          </Label>
          <input
            id="confirm-delete"
            type="text"
            autoComplete="off"
            value={confirmation}
            onChange={(e) => setConfirmation(e.target.value)}
            placeholder="DELETE"
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          />
          <p className="text-xs text-muted-foreground">
            Signed in as <code>@{login}</code>.
          </p>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => setOpen(false)}
            disabled={pending}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={confirm}
            disabled={!canDelete || pending}
          >
            {pending ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <Trash2 className="mr-2 size-4" />
            )}
            {pending ? "Deleting…" : "Delete everything"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
