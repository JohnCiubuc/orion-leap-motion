<script>
  // Raw stereo IR feed. Bytes go straight into a WebGL texture; a shader maps brightness to colour.
  import { onIR } from "../lib/link.svelte.js";

  let { palette = "night" } = $props(); // "night" | "gray"
  let canvas, size = $state("");

  const VS = `#version 300 es
    in vec2 p; out vec2 uv;
    void main() { uv = vec2(p.x * .5 + .5, .5 - p.y * .5); gl_Position = vec4(p, 0, 1); }`;
  // The texture holds both cameras stacked; show them side by side.
  const FS = `#version 300 es
    precision mediump float; uniform sampler2D img; uniform int pal; in vec2 uv; out vec4 o;
    void main() {
      vec2 t = vec2(fract(uv.x * 2.), uv.y * .5 + step(.5, uv.x) * .5);
      float v = texture(img, t).r;
      vec3 night = mix(vec3(.04, .055, .12), vec3(.56, .78, 1.), smoothstep(.0, .55, v));
      night = mix(night, vec3(1.), smoothstep(.55, 1., v));
      o = vec4(pal == 1 ? vec3(v) : night, 1);
    }`;

  $effect(() => {
    const gl = canvas.getContext("webgl2");
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
    const prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    const palLoc = gl.getUniformLocation(prog, "pal");

    let latest = null, raf;
    const off = onIR((img) => (latest = img));
    const loop = () => {
      raf = requestAnimationFrame(loop);
      if (!latest) return;
      const { width: w, height: h, pixels } = latest;
      latest = null;
      if (!size || canvas.width !== w * 2) (canvas.width = w * 2), (canvas.height = h / 2), (size = `${w}×${h / 2}`);
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.R8, w, h, 0, gl.RED, gl.UNSIGNED_BYTE, pixels);
      gl.uniform1i(palLoc, palette === "gray" ? 1 : 0);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    };
    loop();
    return () => (cancelAnimationFrame(raf), off());
  });
</script>

<div class="ir">
  <canvas bind:this={canvas} width="1280" height="240"></canvas>
  {#if !size}<p class="muted wait">Waiting for the IR stream…</p>{/if}
  <span class="eye l">Left camera</span><span class="eye r">Right camera</span>
</div>

<style>
  .ir { position: relative; border-radius: var(--r-sm); overflow: hidden; background: var(--void); aspect-ratio: 16 / 3; }
  canvas { width: 100%; height: 100%; display: block; image-rendering: auto; }
  .wait { position: absolute; inset: 0; display: grid; place-items: center; }
  .eye { position: absolute; top: 8px; font-size: 11.5px; color: #e6ecffaa; }
  .eye.l { left: 10px; }
  .eye.r { left: calc(50% + 10px); }
</style>
