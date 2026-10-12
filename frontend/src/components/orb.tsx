import { useEffect, useRef } from "react"

export type IrisState = "idle" | "listening" | "thinking" | "speaking"

type Fragment = {
  radius: number
  lat: number
  lon: number
  length: number
  vertical: boolean
  box: boolean
  size: number
  bright: number
  drift: number
  seed: number
}

type Ring = { radius: number; tiltX: number; tiltZ: number; start: number; span: number; speed: number; width: number }

type Vec = { x: number; y: number; z: number }

const PROFILE: Record<IrisState, { spin: number; spread: number; glow: number; hue: number }> = {
  idle: { spin: 0.18, spread: 0.02, glow: 0.65, hue: 40 },
  listening: { spin: 0.3, spread: 0.06, glow: 0.9, hue: 44 },
  thinking: { spin: 1.1, spread: 0.04, glow: 0.85, hue: 34 },
  speaking: { spin: 0.45, spread: 0.08, glow: 1, hue: 42 },
}

function random(seed: number) {
  let state = seed
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296
    return state / 4294967296
  }
}

function buildScene() {
  const rand = random(7)
  const fragments: Fragment[] = []
  for (let i = 0; i < 950; i++) {
    const shell = rand()
    fragments.push({
      radius: shell < 0.65 ? 0.88 + rand() * 0.14 : 0.35 + rand() * 0.5,
      lat: Math.asin(rand() * 2 - 1),
      lon: rand() * Math.PI * 2,
      length: 0.04 + rand() * rand() * 0.35,
      vertical: rand() < 0.3,
      box: rand() < 0.12,
      size: 0.02 + rand() * 0.05,
      bright: 0.35 + rand() * 0.65,
      drift: (rand() - 0.5) * 0.25,
      seed: rand() * 100,
    })
  }
  const rings: Ring[] = []
  for (let i = 0; i < 9; i++) {
    rings.push({
      radius: 0.55 + rand() * 0.5,
      tiltX: (rand() - 0.5) * Math.PI,
      tiltZ: (rand() - 0.5) * Math.PI,
      start: rand() * Math.PI * 2,
      span: Math.PI * (0.4 + rand() * 1.3),
      speed: (rand() - 0.5) * 0.9,
      width: 0.6 + rand() * 1.6,
    })
  }
  return { fragments, rings }
}

function rotate(p: Vec, yaw: number, pitch: number): Vec {
  const cy = Math.cos(yaw)
  const sy = Math.sin(yaw)
  const x = p.x * cy + p.z * sy
  const z = -p.x * sy + p.z * cy
  const cp = Math.cos(pitch)
  const sp = Math.sin(pitch)
  return { x, y: p.y * cp - z * sp, z: p.y * sp + z * cp }
}

function spherical(radius: number, lat: number, lon: number): Vec {
  return { x: radius * Math.cos(lat) * Math.sin(lon), y: radius * Math.sin(lat), z: radius * Math.cos(lat) * Math.cos(lon) }
}

export function Orb({ state, level, onClick }: { state: IrisState; level: number; onClick: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const live = useRef({ state, level })
  live.current = { state, level }

  useEffect(() => {
    const element = canvas.current!
    const context = element.getContext("2d")!
    const layer = document.createElement("canvas")
    const ink = layer.getContext("2d")!
    const { fragments, rings } = buildScene()
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    let frame = 0
    let energy = 0
    let spin = PROFILE.idle.spin
    let spread = PROFILE.idle.spread
    let glow = PROFILE.idle.glow
    let hue = PROFILE.idle.hue
    let yaw = 0
    let clock = 0
    let last = performance.now()

    const resize = () => {
      const ratio = window.devicePixelRatio || 1
      element.width = layer.width = element.clientWidth * ratio
      element.height = layer.height = element.clientHeight * ratio
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(element)

    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000) * (reduced ? 0.2 : 1)
      last = now
      const { state: current, level: rawLevel } = live.current
      const profile = PROFILE[current]
      const target = current === "speaking" && rawLevel === 0 ? 0.25 + 0.3 * Math.abs(Math.sin(now / 130) * Math.sin(now / 410)) : rawLevel
      energy += (target - energy) * Math.min(1, dt * 12)
      spin += (profile.spin - spin) * Math.min(1, dt * 2)
      spread += (profile.spread - spread) * Math.min(1, dt * 3)
      glow += (profile.glow - glow) * Math.min(1, dt * 3)
      hue += (profile.hue - hue) * Math.min(1, dt * 2)
      yaw += dt * spin
      clock += dt

      const { width, height } = element
      const cx = width / 2
      const cy = height / 2
      const scale = Math.min(width, height) * 0.3 * (1 + energy * 0.08)
      const pitch = 0.35 + Math.sin(clock * 0.21) * 0.08
      const project = (p: Vec) => {
        const perspective = 3 / (3 - p.z)
        return { x: cx + p.x * scale * perspective, y: cy - p.y * scale * perspective, depth: (p.z + 1.1) / 2.2 }
      }

      ink.clearRect(0, 0, width, height)
      ink.globalCompositeOperation = "lighter"
      ink.lineCap = "round"

      for (const f of fragments) {
        const burst = spread + energy * 0.35 * (0.5 + 0.5 * Math.sin(clock * 3 + f.seed))
        const radius = f.radius * (1 + (f.radius > 0.85 ? burst : burst * 0.3))
        const lon = f.lon + clock * f.drift
        const head = project(rotate(spherical(radius, f.lat, lon), yaw, pitch))
        const alpha = f.bright * (0.15 + head.depth * 0.85) * glow
        if (alpha < 0.05) continue
        const light = 55 + f.bright * 25
        ink.strokeStyle = `hsla(${hue + f.bright * 8}, 100%, ${light}%, ${alpha})`
        ink.lineWidth = (0.6 + f.bright * 1.2) * (window.devicePixelRatio || 1)
        ink.beginPath()
        if (f.box) {
          const s = f.size
          const corners = [
            [-s, -s * 0.7],
            [s, -s * 0.7],
            [s, s * 0.7],
            [-s, s * 0.7],
          ].map(([dLon, dLat]) => project(rotate(spherical(radius, f.lat + dLat, lon + dLon / Math.max(0.3, Math.cos(f.lat))), yaw, pitch)))
          ink.moveTo(corners[0].x, corners[0].y)
          for (const c of corners.slice(1)) ink.lineTo(c.x, c.y)
          ink.closePath()
        } else {
          ink.moveTo(head.x, head.y)
          for (let k = 1; k <= 4; k++) {
            const step = (f.length * k) / 4
            const point = f.vertical
              ? spherical(radius, Math.max(-1.55, Math.min(1.55, f.lat + step)), lon)
              : spherical(radius, f.lat, lon + step / Math.max(0.3, Math.cos(f.lat)))
            const screen = project(rotate(point, yaw, pitch))
            ink.lineTo(screen.x, screen.y)
          }
        }
        ink.stroke()
      }

      for (const ring of rings) {
        const start = ring.start + clock * ring.speed * (1 + spin)
        ink.lineWidth = ring.width * (window.devicePixelRatio || 1)
        let previous: ReturnType<typeof project> | null = null
        for (let i = 0; i <= 64; i++) {
          const t = start + (ring.span * i) / 64
          let p: Vec = { x: Math.cos(t) * ring.radius, y: 0, z: Math.sin(t) * ring.radius }
          p = rotate(p, ring.tiltZ, ring.tiltX)
          const screen = project(rotate(p, yaw * 0.6, pitch))
          if (previous) {
            ink.strokeStyle = `hsla(${hue + 4}, 100%, 68%, ${(0.1 + screen.depth * 0.55) * glow})`
            ink.beginPath()
            ink.moveTo(previous.x, previous.y)
            ink.lineTo(screen.x, screen.y)
            ink.stroke()
          }
          previous = screen
        }
      }

      const coreRadius = scale * (0.16 + energy * 0.08)
      const core = ink.createRadialGradient(cx, cy, 0, cx, cy, coreRadius * 2.4)
      core.addColorStop(0, `hsla(${hue + 12}, 100%, 92%, ${0.75 * glow})`)
      core.addColorStop(0.35, `hsla(${hue}, 100%, 60%, ${0.35 * glow})`)
      core.addColorStop(1, `hsla(${hue - 6}, 100%, 45%, 0)`)
      ink.fillStyle = core
      ink.beginPath()
      ink.arc(cx, cy, coreRadius * 2.4, 0, Math.PI * 2)
      ink.fill()
      ink.lineWidth = 1.4 * (window.devicePixelRatio || 1)
      for (let i = 0; i < 3; i++) {
        ink.strokeStyle = `hsla(${hue + 10}, 100%, 75%, ${0.55 * glow})`
        ink.beginPath()
        ink.ellipse(cx, cy, coreRadius * (1 + i * 0.35), coreRadius * (0.45 + i * 0.2), clock * (0.8 + i * 0.5) * (i % 2 ? -1 : 1), 0, Math.PI * 1.6)
        ink.stroke()
      }

      context.clearRect(0, 0, width, height)
      context.globalCompositeOperation = "lighter"
      context.filter = `blur(${Math.round(scale * 0.05)}px)`
      context.globalAlpha = 0.9
      context.drawImage(layer, 0, 0)
      context.filter = "none"
      context.globalAlpha = 1
      context.drawImage(layer, 0, 0)
      context.globalCompositeOperation = "source-over"

      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  const press = useRef<{ x: number; y: number } | null>(null)

  return (
    <button
      type="button"
      onMouseDown={(e) => (press.current = { x: e.screenX, y: e.screenY })}
      onClick={(e) => {
        const start = press.current
        press.current = null
        if (start && Math.hypot(e.screenX - start.x, e.screenY - start.y) > 5) return
        onClick()
      }}
      aria-label="Falar com a Iris (arraste para mover)"
      title="Toque para falar, arraste para mover"
      className="pywebview-drag-region absolute inset-0 cursor-pointer rounded-full outline-none"
    >
      <canvas ref={canvas} className="size-full" />
    </button>
  )
}
