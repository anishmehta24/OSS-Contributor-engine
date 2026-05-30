"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

export type Filters = {
  difficulty: "any" | "easy" | "medium" | "hard";
  top: number;
  explain: boolean;
};

const DIFFICULTIES: Filters["difficulty"][] = ["any", "easy", "medium", "hard"];
const TOP_OPTIONS = [5, 10, 20, 30];

export function FilterBar({ filters }: { filters: Filters }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [, startTransition] = React.useTransition();

  function updateParam(key: string, value: string) {
    const updated = new URLSearchParams(params);
    updated.set(key, value);
    startTransition(() => {
      router.push(`${pathname}?${updated.toString()}`);
    });
  }

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="space-y-1.5">
        <Label htmlFor="difficulty" className="text-xs uppercase tracking-wide text-muted-foreground">
          Difficulty
        </Label>
        <Select
          value={filters.difficulty}
          onValueChange={(v) => updateParam("difficulty", String(v))}
        >
          <SelectTrigger id="difficulty" className="min-w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DIFFICULTIES.map((d) => (
              <SelectItem key={d} value={d}>
                <span className="capitalize">{d}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="top" className="text-xs uppercase tracking-wide text-muted-foreground">
          Show top
        </Label>
        <Select
          value={String(filters.top)}
          onValueChange={(v) => updateParam("top", String(v))}
        >
          <SelectTrigger id="top" className="min-w-24">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TOP_OPTIONS.map((n) => (
              <SelectItem key={n} value={String(n)}>
                {n}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-2 pb-2">
        <Switch
          id="explain"
          checked={filters.explain}
          onCheckedChange={(v) => updateParam("explain", String(v))}
        />
        <Label htmlFor="explain" className="text-sm cursor-pointer">
          Explain matches
        </Label>
      </div>
    </div>
  );
}
