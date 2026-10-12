import { Minus, Power, X } from "lucide-react"

import type { IrisApi } from "@/lib/bridge"

export function WindowControls({ api }: { api: IrisApi | null }) {
  return (
    <header className="pywebview-drag-region absolute inset-x-[25%] top-0 z-20 flex h-[16%] items-end justify-center pb-1">
      <div className="flex items-center opacity-0 transition-opacity duration-300 group-hover/app:opacity-100 focus-within:opacity-100">
        <ControlButton label="Minimizar" onClick={() => api?.minimize()}>
          <Minus />
        </ControlButton>
        <ControlButton label="Esconder (continua ouvindo “Iris”)" onClick={() => api?.close()}>
          <X />
        </ControlButton>
        <ControlButton label="Desligar a Iris" onClick={() => api?.quit()} danger>
          <Power />
        </ControlButton>
      </div>
    </header>
  )
}

function ControlButton({ label, onClick, danger, children }: { label: string; onClick: () => void; danger?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={`grid size-8 place-items-center rounded-full bg-black/60 text-muted-foreground transition-colors [&_svg]:size-3.5 ${
        danger ? "hover:bg-destructive/20 hover:text-destructive" : "hover:bg-white/10 hover:text-foreground"
      }`}
    >
      {children}
    </button>
  )
}
