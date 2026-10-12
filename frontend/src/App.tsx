import { Keyboard, Mic, MicOff, MonitorUp, RotateCcw } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { KeyboardInput } from "@/components/keyboard-input"
import { MicMeter } from "@/components/mic-meter"
import { Orb, type IrisState } from "@/components/orb"
import { WindowControls } from "@/components/window-controls"
import { waitForApi, type IrisApi, type WakeEvent } from "@/lib/bridge"
import { cn } from "@/lib/utils"

type Caption = { who: "user" | "iris" | "hint"; text: string; error?: boolean }

const HINT: Caption = { who: "hint", text: "Diga “Iris” ou toque na esfera" }

export default function App() {
  const [api, setApi] = useState<IrisApi | null>(null)
  const [state, setStateValue] = useState<IrisState>("idle")
  const [level, setLevel] = useState(0)
  const [caption, setCaption] = useState<Caption>(HINT)
  const [typing, setTyping] = useState(false)
  const [conversation, setConversation] = useState(true)
  const [voice, setVoice] = useState(true)
  const stateRef = useRef<IrisState>("idle")
  const followUpRef = useRef(10)
  const notesRef = useRef<string[]>([])
  const flushNotesRef = useRef<() => void>(() => {})
  const setState = useCallback((next: IrisState) => {
    stateRef.current = next
    setStateValue(next)
  }, [])

  const speak = useCallback(
    async (text: string) => {
      if (!api) return
      setCaption({ who: "iris", text })
      if (!voice) return
      setState("speaking")
      await api.say(text)
      setState("idle")
    },
    [api, voice, setState],
  )

  const respond = useCallback(
    async (question: string, viaVoice: boolean) => {
      if (!api) return false
      setCaption({ who: "user", text: question })
      setState("thinking")
      const result = await api.converse(question, voice)
      setState("idle")
      if (result.interruptedBy) return respond(result.interruptedBy, true)
      if (result.interrupted) return true
      if (result.ignored) {
        setCaption(HINT)
        return false
      }
      followUpRef.current = result.answer.trim().endsWith("?") ? 10 : 6
      setCaption({ who: "iris", text: result.answer, error: result.error })
      return viaVoice && conversation && !result.error
    },
    [api, voice, conversation, setState],
  )

  const listen = useCallback(
    async (initial?: string) => {
      if (!api || stateRef.current !== "idle") return
      followUpRef.current = 10
      let keepGoing = initial ? await respond(initial, true) : true
      while (keepGoing) {
        setState("listening")
        setCaption({ who: "hint", text: "Ouvindo…" })
        const text = await api.listen(followUpRef.current).catch(() => "")
        setLevel(0)
        if (!text) {
          setState("idle")
          setCaption(HINT)
          return
        }
        keepGoing = await respond(text, true)
      }
    },
    [api, respond, setState],
  )

  const listenRef = useRef(listen)
  listenRef.current = listen
  flushNotesRef.current = async () => {
    if (stateRef.current !== "idle" || !notesRef.current.length) return
    const note = notesRef.current.shift()!
    await speak(note)
    listenRef.current()
  }
  useEffect(() => {
    if (state === "idle") flushNotesRef.current()
  }, [state])
  const speakRef = useRef(speak)
  speakRef.current = speak

  useEffect(() => {
    window.iris = {
      level: (value) => setLevel(value),
      partial: () => {},
      caption: (text) => setCaption({ who: "iris", text }),
      phase: (next) => setState(next),
      notify: (text) => {
        notesRef.current.push(text)
        flushNotesRef.current()
      },
      wake: async (event: WakeEvent) => {
        if (stateRef.current !== "idle") return
        if (event.reply) {
          await speakRef.current(event.reply)
          listenRef.current()
        } else {
          listenRef.current(event.question || undefined)
        }
      },
    }
  }, [])

  useEffect(() => {
    waitForApi().then(async (bridge) => {
      setApi(bridge)
      const boot = await bridge.boot()
      if (boot.notice) {
        setCaption({ who: "iris", text: boot.notice, error: true })
        return
      }
      setTimeout(async () => {
        if (boot.hidden) return
        if (boot.greeting) await speakRef.current(boot.greeting)
        if (boot.voice) listenRef.current()
      }, 300)
    })
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Space" && !typing && (e.target as HTMLElement).tagName !== "INPUT") {
        e.preventDefault()
        listenRef.current()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [typing])

  const reset = async () => {
    await api?.reset()
    setCaption({ who: "hint", text: "Nova conversa. Diga “Iris” ou toque na esfera" })
  }

  return (
    <div className="group/app relative size-full overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-[3%] rounded-full"
        style={{ background: "radial-gradient(circle, rgba(6,5,10,0.86) 0%, rgba(6,5,10,0.78) 55%, rgba(6,5,10,0.35) 68%, transparent 71%)" }}
      />
      <Orb
        state={state}
        level={level}
        onClick={() => (stateRef.current === "speaking" || stateRef.current === "thinking" ? api?.interrupt() : listenRef.current())}
      />
      <WindowControls api={api} />

      <div className="pointer-events-none absolute inset-x-[18%] bottom-[17%] flex flex-col items-center gap-1.5 text-center">
        <p
          key={caption.who}
          className={cn(
            "selectable glow-text pointer-events-auto animate-in rounded-xl bg-black/60 px-3 py-1.5 text-balance fade-in slide-in-from-bottom-1 duration-500",
            caption.who === "hint" && "text-[11px] tracking-wide text-muted-foreground",
            caption.who === "user" && "line-clamp-2 text-xs text-muted-foreground italic",
            caption.who === "iris" && "line-clamp-3 text-[13px] leading-snug text-foreground",
            caption.error && "text-destructive",
          )}
        >
          {caption.text}
        </p>
        <MicMeter level={level} active={state === "listening"} />
      </div>

      <footer className="absolute inset-x-0 bottom-[5%] flex flex-col items-center gap-2">
        {typing && (
          <div className="absolute bottom-12 w-[78%]">
            <KeyboardInput disabled={state !== "idle"} onSend={(text) => respond(text, false)} onClose={() => setTyping(false)} />
          </div>
        )}
        <div
          className={cn(
            "flex items-center gap-0.5 rounded-full border border-white/10 bg-black/80 p-0.5 transition-opacity duration-300",
            "opacity-0 group-hover/app:opacity-100 focus-within:opacity-100",
            typing && "opacity-100",
          )}
        >
          <ToolbarButton label={typing ? "Fechar teclado" : "Escrever"} active={typing} onClick={() => setTyping((v) => !v)}>
            <Keyboard />
          </ToolbarButton>
          <ToolbarButton label={conversation ? "Modo conversa ligado" : "Modo conversa desligado"} active={conversation} onClick={() => setConversation((v) => !v)}>
            {conversation ? <Mic /> : <MicOff />}
          </ToolbarButton>
          <ToolbarButton label={voice ? "Resposta falada ligada" : "Resposta falada desligada"} active={voice} onClick={() => setVoice((v) => !v)}>
            <span className="text-[10px] font-semibold">{voice ? "VOZ" : "MUDO"}</span>
          </ToolbarButton>
          <ToolbarButton label="Próximo monitor" onClick={() => api?.next_screen()}>
            <MonitorUp />
          </ToolbarButton>
          <ToolbarButton label="Nova conversa" onClick={reset}>
            <RotateCcw />
          </ToolbarButton>
        </div>
      </footer>
    </div>
  )
}

function ToolbarButton({ label, active, onClick, children }: { label: string; active?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "grid h-7 min-w-7 place-items-center rounded-full px-1.5 text-muted-foreground transition-colors [&_svg]:size-3.5",
        "hover:bg-white/10 hover:text-foreground",
        active && "bg-white/10 text-foreground",
      )}
    >
      {children}
    </button>
  )
}
