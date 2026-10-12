export type AskResult = { answer: string; error: boolean; interrupted?: boolean; interruptedBy?: string; ignored?: boolean }
export type BootInfo = { listen: boolean; voice: boolean; notice: string | null; version: string; greeting?: string; hidden?: boolean }
export type WakeEvent = { question: string; reply: string }

type IrisApi = {
  boot(): Promise<BootInfo>
  ask(question: string): Promise<AskResult>
  converse(question: string, speak: boolean): Promise<AskResult>
  say(text: string): Promise<void>
  listen(timeout?: number): Promise<string>
  reset(): Promise<void>
  minimize(): Promise<void>
  toggle_maximize(): Promise<void>
  close(): Promise<void>
  interrupt(): Promise<void>
  quit(): Promise<void>
  next_screen(): Promise<void>
}

export type IrisEvents = {
  level: (value: number) => void
  partial: (text: string) => void
  wake: (event: WakeEvent) => void
  caption: (text: string) => void
  phase: (state: "speaking" | "listening") => void
  notify: (text: string) => void
}

declare global {
  interface Window {
    pywebview?: { api: IrisApi }
    iris?: IrisEvents
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const devApi: IrisApi = {
  async boot() {
    return { listen: false, voice: true, notice: null, version: "dev", greeting: "Boa noite! Estou aqui." }
  },
  async ask(question) {
    await sleep(1200)
    return { answer: `Modo de desenvolvimento: você disse "${question}".`, error: false }
  },
  async converse(question, speak) {
    const answer = `Modo de desenvolvimento: você disse "${question}".`
    await sleep(600)
    window.iris?.caption(answer)
    if (speak) {
      window.iris?.phase("speaking")
      await sleep(Math.min(6000, 600 + answer.length * 50))
    }
    return { answer, error: false }
  },
  async say(text) {
    await sleep(Math.min(6000, 600 + text.length * 50))
  },
  async listen() {
    const phrase = "qual a temperatura agora"
    for (let i = 1; i <= phrase.length; i += 3) {
      window.iris?.level(0.2 + Math.random() * 0.6)
      window.iris?.partial(phrase.slice(0, i))
      await sleep(90)
    }
    window.iris?.level(0)
    return phrase
  },
  async reset() {},
  async minimize() {},
  async toggle_maximize() {},
  async close() {},
  async interrupt() {},
  async quit() {},
  async next_screen() {},
}

function readyApi(): IrisApi | null {
  const api = window.pywebview?.api
  return api && typeof api.boot === "function" && typeof api.converse === "function" ? api : null
}

export function waitForApi(): Promise<IrisApi> {
  return new Promise((resolve) => {
    const started = Date.now()
    const poll = () => {
      const api = readyApi()
      if (api) return resolve(api)
      if (import.meta.env.DEV && Date.now() - started > 1500) return resolve(devApi)
      setTimeout(poll, 100)
    }
    poll()
  })
}

export type { IrisApi }
