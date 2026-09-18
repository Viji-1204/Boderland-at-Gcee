// Web Audio API Sound Generator for Borderland UI

class SoundFX {
  constructor() {
    this.ctx = null;
    this.enabled = true;
  }

  init() {
    if (!this.ctx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        this.ctx = new AudioCtx();
      }
    }
    if (this.ctx && this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
  }

  playBeep(freq = 440, type = 'sine', duration = 0.08) {
    if (!this.enabled) return;
    try {
      this.init();
      if (!this.ctx) return;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = type;
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.15, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + duration);
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start();
      osc.stop(this.ctx.currentTime + duration);
    } catch (e) {
      console.warn('Audio FX error:', e);
    }
  }

  click() {
    this.playBeep(600, 'sine', 0.04);
  }

  scanSuccess() {
    if (!this.enabled) return;
    this.playBeep(523.25, 'triangle', 0.1); // C5
    setTimeout(() => this.playBeep(659.25, 'triangle', 0.1), 80); // E5
    setTimeout(() => this.playBeep(783.99, 'triangle', 0.2), 160); // G5
  }

  error() {
    if (!this.enabled) return;
    this.playBeep(180, 'sawtooth', 0.2);
  }

  puzzleSolved() {
    if (!this.enabled) return;
    const notes = [440, 554.37, 659.25, 880];
    notes.forEach((note, idx) => {
      setTimeout(() => this.playBeep(note, 'sine', 0.15), idx * 100);
    });
  }

  attackAlarm() {
    if (!this.enabled) return;
    for (let i = 0; i < 3; i++) {
      setTimeout(() => this.playBeep(800, 'square', 0.1), i * 150);
    }
  }
}

export const sound = new SoundFX();
