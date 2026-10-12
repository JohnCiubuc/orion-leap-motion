// Link to the Orion engine: one WebSocket carrying JSON state + binary live data.
// Reactive state lives in `orion`; high-rate frames go to plain callbacks (no reactivity cost).

const q = new URLSearchParams(location.search);
const WS_URL = `ws://127.0.0.1:${q.get("port") || location.port}/ws?token=${q.get("token") || ""}`;

export const orion = $state({
  connected: false,
  status: {},
  config: null, // last config from the engine
  draft: null, // editable copy (Bindings / Profiles / Settings)
  gestures: [],
  actions: [],
  plugins: [],
  recordings: [],
  feed: [], // recent gesture events, newest first
  flash: {}, // gesture base name → timestamp of last event (UI highlights)
  errors: [],
  notice: null, // { text, ok, at } — short-lived status messages (e.g. controller restart)
  hands: [], // latest decoded hands (updated ~15 Hz for readouts)
  fps: 0,
});

const skeletonSubs = new Set();
const eventSubs = new Set();
const irSubs = new Set();
let ws, lastHands = 0;

// ── Public API ─────────────────────────────────────────────────────────────

export const send = (cmd, args = {}) => ws?.readyState === 1 && ws.send(JSON.stringify({ cmd, ...args }));
export const onSkeleton = (fn) => (skeletonSubs.add(fn), () => skeletonSubs.delete(fn));
export const onGesture = (fn) => (eventSubs.add(fn), () => eventSubs.delete(fn));
export function onIR(fn) {
  irSubs.add(fn);
  send("ir", { on: true });
  return () => (irSubs.delete(fn), irSubs.size || send("ir", { on: false }));
}
export const dirty = () => JSON.stringify(orion.draft) !== JSON.stringify(orion.config);
export const saveDraft = () => send("save_config", { config: $state.snapshot(orion.draft) });
export const discardDraft = () => (orion.draft = structuredClone($state.snapshot(orion.config)));
export const gestureEvents = () => orion.gestures.flatMap((g) => g.events);
export const actionMeta = (name) => orion.actions.find((a) => a.name === name);

// ── Decoding (see orion/frame.py "Binary wire format") ─────────────────────

const PER_HAND = 86;
function decodeSkeleton(buf) {
  const f = new Float32Array(buf.slice(1));
  const hands = [];
  for (let i = 0; i < f[2]; i++) {
    const o = 3 + i * PER_HAND;
    hands.push({
      side: f[o] ? "right" : "left", confidence: f[o + 1], pinch: f[o + 2], grab: f[o + 3],
      extended: f[o + 4], // bitmask: thumb = 1 … pinky = 16
      palm: f.subarray(o + 5, o + 8), normal: f.subarray(o + 8, o + 11),
      joints: f.subarray(o + 11, o + PER_HAND), // 5 fingers × 5 joints × xyz
    });
  }
  return { t: f[0], fps: f[1], hands };
}

function decodeIR(buf) {
  const dv = new DataView(buf);
  return { width: dv.getUint16(1, true), height: dv.getUint16(3, true), pixels: new Uint8Array(buf, 5) };
}

// ── Messages ───────────────────────────────────────────────────────────────

function onState(s) {
  const wasDirty = orion.draft && dirty();
  Object.assign(orion, { status: s.status, gestures: s.gestures, actions: s.actions,
    plugins: s.plugins, recordings: s.recordings, feed: [...s.feed].reverse(), config: s.config });
  if (!wasDirty) discardDraft(); // keep unsaved edits; otherwise follow the engine (hand edits)
}

function onEvent(e) {
  const top = orion.feed[0];
  if (e.phase === "fire" && top?.name === e.name && top.hand === e.hand && e.t - top.t < 1.5) {
    orion.feed[0] = { ...e, count: (top.count ?? 1) + 1 }; // joystick repeats → one row "×N"
  } else orion.feed = [e, ...orion.feed].slice(0, 60);
  orion.flash[e.name.split(".")[0]] = performance.now();
  eventSubs.forEach((fn) => fn(e));
}

function onMessage(m) {
  if (typeof m.data !== "string") {
    const kind = new Uint8Array(m.data, 0, 1)[0];
    if (kind === 83 /* S */) {
      const frame = decodeSkeleton(m.data);
      skeletonSubs.forEach((fn) => fn(frame));
      const now = performance.now();
      if (now - lastHands > 66) (lastHands = now), (orion.hands = frame.hands), (orion.fps = frame.fps);
    } else if (kind === 73 /* I */) {
      const img = decodeIR(m.data);
      irSubs.forEach((fn) => fn(img));
    }
    return;
  }
  const msg = JSON.parse(m.data);
  if (msg.type === "state") onState(msg.state);
  else if (msg.type === "status") orion.status = msg.status;
  else if (msg.type === "event") onEvent(msg.event);
  else if (msg.type === "notice") orion.notice = msg.notice && { ...msg.notice, at: Date.now() };
  else if (msg.type === "error") orion.errors = [{ ...msg.error, at: Date.now() }, ...orion.errors].slice(0, 5);
}

// ── Connection (auto-reconnect) ────────────────────────────────────────────

function connect() {
  ws = new WebSocket(WS_URL);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    orion.connected = true;
    if (irSubs.size) send("ir", { on: true });
  };
  ws.onmessage = onMessage;
  ws.onclose = () => ((orion.connected = false), setTimeout(connect, 1000));
}
connect();
