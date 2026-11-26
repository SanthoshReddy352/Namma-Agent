import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

async function load(status) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => status })));
  return import("../voice.js");
}

describe("OS voice — WAV encoding", () => {
  it("writes a 16-bit mono PCM WAV header and clamps samples", async () => {
    const { encodeWav } = await load(null);
    const blob = encodeWav(new Float32Array([0, 1, -1, 2]), 16000);
    const ab = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsArrayBuffer(blob); });
    const buf = new DataView(ab);
    const tag = (o) => String.fromCharCode(...[0, 1, 2, 3].map((i) => buf.getUint8(o + i)));
    expect(tag(0)).toBe("RIFF");
    expect(tag(8)).toBe("WAVE");
    expect(buf.getUint16(22, true)).toBe(1);          // mono
    expect(buf.getUint32(24, true)).toBe(16000);      // sample rate
    expect(buf.getUint16(34, true)).toBe(16);         // bits
    expect(buf.getUint32(40, true)).toBe(8);          // 4 samples × 2 bytes
    expect(buf.getInt16(46, true)).toBe(32767);       // +1.0
    expect(buf.getInt16(48, true)).toBe(-32768);      // -1.0
    expect(buf.getInt16(50, true)).toBe(32767);       // 2.0 clamped
  });

  it("downsamples 48 kHz to 16 kHz by averaging", async () => {
    const { downsample } = await load(null);
    const out = downsample(new Float32Array([0, 0.3, 0.6, 1, 1, 1]), 48000, 16000);
    expect(out.length).toBe(2);
    expect(out[0]).toBeCloseTo(0.3);
    expect(out[1]).toBeCloseTo(1);
  });
});

describe("OS voice — engine choice", () => {
  it("prefers the system engines and honours an explicit Browser choice", async () => {
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: () => {} }, language: "en-US" });
    let v = await load({ tts: { system: true }, stt: { system: true }, prefs: { tts_engine: "auto", stt_engine: "auto" } });
    expect(await v.dictationEngine()).toBe("server");
    expect(await v.speechEngine()).toBe("server");
    v.setVoicePrefs({ stt_engine: "browser", tts_engine: "browser" });
    window.webkitSpeechRecognition = function SR() {};
    window.speechSynthesis = { cancel() {}, speak() {} };
    expect(await v.dictationEngine()).toBe("browser");
    expect(await v.speechEngine()).toBe("browser");
    delete window.webkitSpeechRecognition;
    delete window.speechSynthesis;
  });

  it("falls back to the browser when the server has no engine", async () => {
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia: () => {} }, language: "en-US" });
    window.webkitSpeechRecognition = function SR() {};
    const v = await load({ tts: { system: false }, stt: { system: false, cloud: false }, prefs: {} });
    expect(await v.dictationEngine()).toBe("browser");
    delete window.webkitSpeechRecognition;
  });

  it("strips markdown before speaking", async () => {
    const { toPlainText } = await load(null);
    expect(toPlainText("## Title\n\n**bold** and `code` [link](http://x)")).toBe("Title. bold and code link");
  });
});
