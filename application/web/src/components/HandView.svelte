<script>
  // Live 3D hands, drawn as constellations: joints are stars, bones are faint lines.
  import * as THREE from "three";
  import { OrbitControls } from "three/addons/controls/OrbitControls.js";
  import { onSkeleton, onGesture } from "../lib/link.svelte.js";

  let el;
  const MM = 0.01; // Leap millimetres → scene units
  const COLORS = { left: 0x8fc7ff, right: 0xffa463 };
  const TRAIL = 70;

  // Bone index pairs over the 25 joints (finger f, joint j → f*5+j), plus the knuckle arc
  const BONES = [];
  for (let f = 0; f < 5; f++) for (let j = 0; j < 4; j++) BONES.push(f * 5 + j, f * 5 + j + 1);
  for (let f = 1; f < 4; f++) BONES.push(f * 5 + 1, (f + 1) * 5 + 1);
  BONES.push(1 * 5 + 0, 4 * 5 + 0, 0, 1 * 5 + 1);

  function glowTexture() {
    const c = Object.assign(document.createElement("canvas"), { width: 64, height: 64 });
    const g = c.getContext("2d"), r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    [[0, "#fff"], [0.18, "#ffffffee"], [0.42, "#ffffff44"], [1, "#fff0"]].forEach(([o, col]) => r.addColorStop(o, col));
    g.fillStyle = r;
    g.fillRect(0, 0, 64, 64);
    return new THREE.CanvasTexture(c);
  }

  // ── One hand = joints (stars) + tips/palm (bright stars) + bones + index-tip trail ──
  function makeHand(scene, tex) {
    const joints = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(75), 3));
    const bright = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(18), 3));
    const bones = new THREE.BufferGeometry().setAttribute("position", joints.getAttribute("position"));
    bones.setIndex(BONES);
    const trail = new THREE.BufferGeometry()
      .setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(TRAIL * 3), 3))
      .setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(TRAIL * 3), 3));
    const pm = (size) => new THREE.PointsMaterial({ size, map: tex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
    const tether = new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(6), 3));
    const h = {
      group: new THREE.Group(), joints, bright, trail, tether, anchor: null, tip: [], color: new THREE.Color(),
      mats: [pm(0.16), pm(0.42), new THREE.LineBasicMaterial({ transparent: true, opacity: 0.38 }),
             new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, blending: THREE.AdditiveBlending })],
    };
    // Joystick tether: anchor star where the pinch/grab began, line to the palm now
    h.tetherObj = new THREE.Group();
    h.tetherObj.add(new THREE.Points(tether, pm(0.5)), new THREE.Line(tether, new THREE.LineBasicMaterial({ transparent: true, opacity: 0.7 })));
    h.group.add(new THREE.Points(joints, h.mats[0]), new THREE.Points(bright, h.mats[1]),
                new THREE.LineSegments(bones, h.mats[2]), new THREE.Line(trail, h.mats[3]), h.tetherObj);
    h.group.traverse((o) => (o.frustumCulled = false)); // geometry moves every frame
    scene.add(h.group);
    return h;
  }

  function updateHand(h, d) {
    h.mats.slice(0, 3).forEach((m) => m.color.setHex(COLORS[d.side]));
    h.color.setHex(COLORS[d.side]);
    const jp = h.joints.getAttribute("position").array, bp = h.bright.getAttribute("position").array;
    for (let i = 0; i < 75; i++) jp[i] = d.joints[i] * MM;
    for (let f = 0; f < 5; f++) for (let k = 0; k < 3; k++) bp[f * 3 + k] = jp[(f * 5 + 4) * 3 + k];
    for (let k = 0; k < 3; k++) bp[15 + k] = d.palm[k] * MM;
    const tip = [jp[27], jp[28], jp[29]], last = h.tip.at(-1); // index fingertip
    if (last && Math.hypot(tip[0] - last[0], tip[1] - last[1], tip[2] - last[2]) > 0.4) h.tip.length = 0; // jump → new trail
    h.tip.push(tip);
    if (h.tip.length > TRAIL) h.tip.shift();
    const tp = h.trail.getAttribute("position").array, tc = h.trail.getAttribute("color").array;
    h.tip.forEach((p, i) => {
      const a = (i / h.tip.length) ** 2 * 0.8; // fade out along the trail
      tp.set(p, i * 3);
      tc.set([h.color.r * a, h.color.g * a, h.color.b * a], i * 3);
    });
    h.trail.setDrawRange(0, h.tip.length);
    h.tetherObj.visible = !!h.anchor;
    if (h.anchor) {
      h.tetherObj.children.forEach((o) => o.material.color.setHex(COLORS[d.side]));
      h.tether.getAttribute("position").array.set([...h.anchor.map((v) => v * MM), d.palm[0] * MM, d.palm[1] * MM, d.palm[2] * MM]);
      h.tether.getAttribute("position").needsUpdate = true;
      h.tether.setDrawRange(0, 2);
    }
    for (const g of [h.joints, h.bright, h.trail]) for (const a of Object.values(g.attributes)) a.needsUpdate = true;
  }

  // ── Static scene: starfield, star-chart floor, device ──
  function decor(scene) {
    const stars = new Float32Array(1800);
    for (let i = 0; i < 600; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(18 + Math.random() * 14);
      stars.set([v.x, Math.abs(v.y) * 0.9 + 0.5, v.z], i * 3);
    }
    scene.add(new THREE.Points(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(stars, 3)),
      new THREE.PointsMaterial({ size: 1.6, sizeAttenuation: false, color: 0x7c88b8, transparent: true, opacity: 0.75, fog: false })));
    const chart = new THREE.Group(), lm = new THREE.LineBasicMaterial({ color: 0x2a3670, transparent: true, opacity: 0.7 });
    for (const r of [1, 2, 3, 4]) {
      const pts = Array.from({ length: 97 }, (_, i) => new THREE.Vector3(Math.cos(i / 96 * Math.PI * 2) * r, 0, Math.sin(i / 96 * Math.PI * 2) * r));
      chart.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lm));
    }
    for (let a = 0; a < 12; a++) {
      const v = new THREE.Vector3(Math.cos(a * Math.PI / 6), 0, Math.sin(a * Math.PI / 6));
      chart.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([v.clone().multiplyScalar(0.6), v.multiplyScalar(4)]), lm));
    }
    scene.add(chart);
    const device = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.11, 0.3), new THREE.MeshBasicMaterial({ color: 0x151b38 }));
    device.position.y = 0.055;
    const lens = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.005, 0.12), new THREE.MeshBasicMaterial({ color: 0x8f3a4a }));
    lens.position.y = 0.112;
    scene.add(device, lens);
  }

  $effect(() => {
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setClearColor(0x0a0e1f);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x0a0e1f, 6, 22);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 4.4, 3.7);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 2.0, 0);
    Object.assign(controls, { enableDamping: true, enablePan: false, minDistance: 2.5, maxDistance: 11, maxPolarAngle: Math.PI * 0.55 });
    decor(scene);
    const tex = glowTexture(), hands = [makeHand(scene, tex), makeHand(scene, tex)];

    let latest = null, raf;
    const off = onSkeleton((f) => (latest = f));
    const offG = onGesture((e) => { // follow joystick reference points per hand (they move on every step)
      if (!e.name.split(".")[0].endsWith("_joy")) return;
      hands[e.hand === "right" ? 1 : 0].anchor = e.phase === "end" ? null : e.value;
    });
    const resize = new ResizeObserver(() => {
      const { clientWidth: w, clientHeight: h } = el;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    });
    resize.observe(el);
    const loop = () => {
      raf = requestAnimationFrame(loop);
      if (latest) {
        hands.forEach((h, i) => {
          const d = latest.hands.find((x) => x.side === (i ? "right" : "left")); // stable slot per side
          h.group.visible = !!d;
          if (d) updateHand(h, d);
          else h.tip.length = 0;
        });
        latest = null;
      }
      controls.update();
      renderer.render(scene, camera);
    };
    loop();
    return () => (cancelAnimationFrame(raf), off(), offG(), resize.disconnect(), controls.dispose(), renderer.dispose(), renderer.domElement.remove());
  });
</script>

<div class="view" bind:this={el}></div>

<style>
  .view { position: absolute; inset: 0; }
  .view :global(canvas) { display: block; cursor: grab; }
  .view :global(canvas:active) { cursor: grabbing; }
</style>
