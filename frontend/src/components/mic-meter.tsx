import { Mic } from "lucide-react"

import { cn } from "@/lib/utils"

const BARS = [0.5, 0.8, 1, 0.8, 0.5]

export function MicMeter({ level, active }: { level: number; active: boolean }) {
  const hearing = level > 0.04
  return (
    <div
      className={cn("flex h-4 items-center gap-1 transition-opacity", hearing || active ? "opacity-100" : "opacity-50")}
      title={hearing ? "Captando sua voz" : "Microfone ligado"}
      aria-label={hearing ? "Captando sua voz" : "Microfone ligado"}
    >
      <Mic className={cn("size-3", hearing ? "text-primary" : "text-muted-foreground")} />
      <div className="flex h-3 items-center gap-[2px]">
        {BARS.map((weight, index) => (
          <span
            key={index}
            className="w-[2px] rounded-full bg-primary transition-[height] duration-75"
            style={{ height: `${Math.max(15, Math.min(100, level * 260 * weight))}%` }}
          />
        ))}
      </div>
    </div>
  )
}
