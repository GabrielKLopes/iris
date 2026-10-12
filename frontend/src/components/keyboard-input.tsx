import { ArrowUp } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"

export function KeyboardInput({ disabled, onSend, onClose }: { disabled: boolean; onSend: (text: string) => void; onClose: () => void }) {
  const [text, setText] = useState("")
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => ref.current?.focus(), [])

  const submit = () => {
    const value = text.trim()
    if (!value || disabled) return
    onSend(value)
    setText("")
  }

  return (
    <div className="flex w-full max-w-lg animate-in items-center gap-2 rounded-full border border-white/10 bg-black/50 p-1.5 pl-5 fade-in slide-in-from-bottom-2">
      <input
        ref={ref}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit()
          if (e.key === "Escape") onClose()
        }}
        placeholder="Escreva para a Iris…"
        className="selectable h-9 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-foreground"
      />
      <Button size="icon-lg" aria-label="Enviar" disabled={disabled || !text.trim()} onClick={submit} className="rounded-full">
        <ArrowUp />
      </Button>
    </div>
  )
}
