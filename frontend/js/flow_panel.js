/**
 * flow_panel.js — 水膜流场可视化面板
 * 集成：SPH水膜粒子 + 功耗趋势曲线 + 压力分布曲线
 * 依赖：Chart.js
 */
(function (global) {
  'use strict';

  // ========== 1. SPH 粒子子系统 ==========
  class WendlandKernel {
    constructor(h = 10) {
      this.h = h;
      this.h2 = h * h;
      this.h3 = h * h * h;
      this.alpha = 7 / (64 * Math.PI * this.h3);
    }
    evaluate(r) {
      if (r > this.h) return 0;
      const q = r / this.h;
      const term = (1 - q / 2);
      return this.alpha * term * term * term * term * (2 * q + 1);
    }
    gradient(r, x, y) {
      if (r > this.h || r < 1e-8) return { x: 0, y: 0 };
      const q = r / this.h;
      const term = (1 - q / 2);
      const dW_dq = this.alpha * (-2 * term * term * term * (2 * q + 1) + term * term * term * term * 2);
      const dq_dr = 1 / this.h;
      const dW_dr = dW_dq * dq_dr;
      return { x: dW_dr * x / r, y: dW_dr * y / r };
    }
    laplacian(r) {
      if (r > this.h || r < 1e-8) return 0;
      const q = r / this.h;
      const term = (1 - q / 2);
      return 10 * this.alpha * (term * term) * (3 * q * q - 2 * q - 4) / (this.h * this.h);
    }
  }

  class SPHParticle {
    constructor(x, y) {
      this.x = x; this.y = y;
      this.vx = 0; this.vy = 0;
      this.ax = 0; this.ay = 0;
      this.density = 0; this.pressure = 0;
      this.mass = 1.0;
      this.color = '#4fc3f7';
      this.phase = 'water';
      this.isInCavitation = false;
    }
  }

  class SPHSolver {
    constructor(opts) {
      opts = opts || {};
      this.R_inner = opts.R_inner != null ? opts.R_inner : 120;
      this.R_outer = opts.R_outer != null ? opts.R_outer : 140;
      this.centerX = opts.centerX || 0;
      this.centerY = opts.centerY || 0;
      this.particleCount = opts.particleCount || 500;
      this.kernel = new WendlandKernel(opts.kernelH || 10);
      this.restDensity = opts.restDensity || 1000;
      this.gamma = opts.gamma || 1.5;
      this.mu = opts.viscosity || 0.5;
      this.dt = opts.dt || 0.016;
      this.damping = opts.damping != null ? opts.damping : 0.998;
      this.boundaryK = opts.boundaryK || 8000;
      this.reflectionCoeff = opts.reflectionCoeff != null ? opts.reflectionCoeff : 0.2;
      this.couetteDrag = opts.couetteDrag != null ? opts.couetteDrag : 2.0;
      this.rpm = 0;
      this.eccentricity = 0;
      this.particles = [];
      this.neighborList = new Map();
      this._initParticles();
    }
    _initParticles() {
      this.particles = [];
      const R_inner = this.R_inner, R_outer = this.R_outer;
      const count = this.particleCount;
      for (let i = 0; i < count; i++) {
        const t = Math.random() * Math.PI * 2;
        const r = R_inner + 0.5 + Math.random() * (R_outer - R_inner - 1);
        this.particles.push(new SPHParticle(
          this.centerX + Math.cos(t) * r,
          this.centerY + Math.sin(t) * r,
        ));
      }
    }
    buildNeighborList() {
      this.neighborList.clear();
      const cell = this.kernel.h;
      const grid = new Map();
      for (let i = 0; i < this.particles.length; i++) {
        const p = this.particles[i];
        const gx = Math.floor(p.x / cell), gy = Math.floor(p.y / cell);
        const k = gx + '_' + gy;
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push(i);
      }
      for (let i = 0; i < this.particles.length; i++) {
        const p = this.particles[i];
        const gx = Math.floor(p.x / cell), gy = Math.floor(p.y / cell);
        const neighbors = [];
        for (let dx = -1; dx <= 1; dx++)
          for (let dy = -1; dy <= 1; dy++) {
            const list = grid.get((gx + dx) + '_' + (gy + dy));
            if (!list) continue;
            for (const j of list) {
              if (j === i) continue;
              const pj = this.particles[j];
              const rx = pj.x - p.x, ry = pj.y - p.y;
              if (rx * rx + ry * ry < this.kernel.h2) neighbors.push(j);
            }
          }
        this.neighborList.set(i, neighbors);
      }
    }
    getNeighbors(i) { return this.neighborList.get(i) || []; }
    computeDensity() {
      for (let i = 0; i < this.particles.length; i++) {
        const pi = this.particles[i];
        pi.density = pi.mass * this.kernel.evaluate(0);
        for (const j of this.getNeighbors(i)) {
          const pj = this.particles[j];
          const r = Math.hypot(pj.x - pi.x, pj.y - pi.y);
          pi.density += pj.mass * this.kernel.evaluate(r);
        }
      }
    }
    computePressure() {
      for (const p of this.particles) p.pressure = this.gamma * (p.density - this.restDensity);
    }
    computeAccelerations() {
      for (let i = 0; i < this.particles.length; i++) {
        const pi = this.particles[i];
        let ax = 0, ay = 0;
        for (const j of this.getNeighbors(i)) {
          const pj = this.particles[j];
          const dx = pj.x - pi.x, dy = pj.y - pi.y;
          const r = Math.hypot(dx, dy);
          if (r < 1e-8) continue;
          const pTerm = pj.mass * (pi.pressure + pj.pressure) / (2 * pj.density * this.restDensity);
          const g = this.kernel.gradient(r, dx, dy);
          ax -= pTerm * g.x; ay -= pTerm * g.y;
          const viscLap = this.kernel.laplacian(r);
          const vx = pj.vx - pi.vx, vy = pj.vy - pi.vy;
          ax += this.mu * (pj.mass / pj.density) * vx * viscLap;
          ay += this.mu * (pj.mass / pj.density) * vy * viscLap;
        }
        pi.ax = ax; pi.ay = ay;
      }
      this.applyCouetteDrag();
      this.applyBoundaryPenalty();
    }
    applyCouetteDrag() {
      const omega = (this.rpm || 0) * 2 * Math.PI / 60;
      const U = omega * this.R_inner;
      for (const p of this.particles) {
        const dx = p.x - this.centerX, dy = p.y - this.centerY;
        const r = Math.hypot(dx, dy);
        if (r < 1e-6) continue;
        const tx = -dy / r, ty = dx / r;
        const gap = this.R_outer - this.R_inner;
        const frac = Math.max(0, Math.min(1, (r - this.R_inner) / gap));
        const uTarget = U * (1 - frac * 0.7);
        const vCur = p.vx * tx + p.vy * ty;
        p.ax += this.couetteDrag * (uTarget * tx - (p.vx - vCur * tx));
        p.ay += this.couetteDrag * (uTarget * ty - (p.vy - vCur * ty));
      }
    }
    applyBoundaryPenalty() {
      for (const p of this.particles) {
        const dx = p.x - this.centerX, dy = p.y - this.centerY;
        const r = Math.hypot(dx, dy);
        if (r < 1e-6) continue;
        const nx = dx / r, ny = dy / r;
        if (r < this.R_inner) {
          const delta = this.R_inner - r;
          p.ax += this.boundaryK * delta * delta * nx;
          p.ay += this.boundaryK * delta * delta * ny;
        } else if (r > this.R_outer) {
          const delta = r - this.R_outer;
          p.ax -= this.boundaryK * delta * delta * nx;
          p.ay -= this.boundaryK * delta * delta * ny;
        }
      }
    }
    enforceBoundaryReflection() {
      for (const p of this.particles) {
        const dx = p.x - this.centerX, dy = p.y - this.centerY;
        const r = Math.hypot(dx, dy);
        if (r < 1e-6) continue;
        const nx = dx / r, ny = dy / r;
        if (r < this.R_inner) {
          const vn = p.vx * nx + p.vy * ny;
          if (vn < 0) { p.vx -= (1 + this.reflectionCoeff) * vn * nx; p.vy -= (1 + this.reflectionCoeff) * vn * ny; }
          p.x = this.centerX + nx * (this.R_inner + 0.5);
          p.y = this.centerY + ny * (this.R_inner + 0.5);
        } else if (r > this.R_outer) {
          const vn = p.vx * nx + p.vy * ny;
          if (vn > 0) { p.vx -= (1 + this.reflectionCoeff) * vn * nx; p.vy -= (1 + this.reflectionCoeff) * vn * ny; }
          p.x = this.centerX + nx * (this.R_outer - 0.5);
          p.y = this.centerY + ny * (this.R_outer - 0.5);
        }
      }
    }
    updateParticlePhase() {
      for (const p of this.particles) {
        const dx = p.x - this.centerX, dy = p.y - this.centerY;
        const theta = Math.atan2(dy, dx);
        const r = Math.hypot(dx, dy);
        const gap = this.R_outer - this.R_inner;
        const frac = (r - this.R_inner) / gap;
        const pres = Math.exp(-Math.pow((theta - 0.5) / 0.8, 2)) * (1 - frac) * 0.9 + 0.05;
        const cavThreshold = 0.05 + 0.02 * (this.rpm / 100);
        p.isInCavitation = pres < cavThreshold;
        p.phase = p.isInCavitation ? 'vapor' : 'water';
        const speed = Math.hypot(p.vx, p.vy);
        if (p.isInCavitation) p.color = 'rgba(255, 180, 100, 0.4)';
        else p.color = `hsl(${200 - speed * 3}, 80%, ${55 + speed}%)`;
      }
    }
    step() {
      this.buildNeighborList();
      this.computeDensity();
      this.computePressure();
      this.computeAccelerations();
      for (const p of this.particles) {
        p.vx += p.ax * this.dt; p.vy += p.ay * this.dt;
        p.vx *= this.damping; p.vy *= this.damping;
        p.x += p.vx * this.dt; p.y += p.vy * this.dt;
      }
      this.enforceBoundaryReflection();
      this.updateParticlePhase();
    }
    findCavitationRegions() {
      const cavPts = this.particles.filter(p => p.isInCavitation);
      if (cavPts.length < 3) return [];
      const visited = new Set();
      const regions = [];
      for (let i = 0; i < cavPts.length; i++) {
        if (visited.has(i)) continue;
        const region = []; const queue = [i]; visited.add(i);
        while (queue.length) {
          const idx = queue.shift(); const p = cavPts[idx]; region.push(p);
          for (let j = 0; j < cavPts.length; j++) {
            if (visited.has(j)) continue;
            const q = cavPts[j];
            if (Math.hypot(p.x - q.x, p.y - q.y) < this.kernel.h * 1.5) { visited.add(j); queue.push(j); }
          }
        }
        if (region.length >= 3) {
          let cx = 0, cy = 0;
          for (const p of region) { cx += p.x; cy += p.y; }
          cx /= region.length; cy /= region.length;
          let rad = 0;
          for (const p of region) rad = Math.max(rad, Math.hypot(p.x - cx, p.y - cy));
          regions.push({ x: cx, y: cy, radius: rad, count: region.length });
        }
      }
      return regions;
    }
  }

  // ========== 2. WaterFilmParticles (Canvas渲染) ==========
  class WaterFilmParticles {
    constructor(canvasId, opts) {
      opts = opts || {};
      this.canvas = document.getElementById(canvasId);
      if (!this.canvas) throw new Error('canvas not found: ' + canvasId);
      this.ctx = this.canvas.getContext('2d');
      this.cx = this.canvas.width / 2;
      this.cy = this.canvas.height / 2;
      this.R_inner = opts.R_inner || 120;
      this.R_outer = opts.R_outer || 140;
      this.solver = new SPHSolver({
        particleCount: opts.particleCount || 500,
        R_inner: this.R_inner, R_outer: this.R_outer,
        centerX: this.cx, centerY: this.cy,
        kernelH: 10, viscosity: 0.5, dt: 0.016,
      });
      this.rpm = 0;
      this.eccentricity = 0;
      this.showVectors = false;
      this.showPressureField = false;
      this.animationId = null;
      this._bindResize();
    }
    _bindResize() {
      const fit = () => {
        const parent = this.canvas.parentElement;
        if (!parent) return;
        const size = Math.min(parent.clientWidth || 400, parent.clientHeight || 400);
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = size * dpr; this.canvas.height = size * dpr;
        this.canvas.style.width = size + 'px'; this.canvas.style.height = size + 'px';
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.cx = size / 2; this.cy = size / 2;
        const scale = size / 400;
        this.R_inner = 120 * scale; this.R_outer = 140 * scale;
        this.solver.R_inner = this.R_inner; this.solver.R_outer = this.R_outer;
        this.solver.centerX = this.cx; this.solver.centerY = this.cy;
        this.solver._initParticles();
      };
      window.addEventListener('resize', fit);
      setTimeout(fit, 10);
    }
    setRPM(r) { this.rpm = r; this.solver.rpm = r; }
    setEccentricity(e) { this.eccentricity = e; this.solver.eccentricity = e; }
    draw() {
      const ctx = this.ctx; const W = this.canvas.clientWidth, H = this.canvas.clientHeight;
      ctx.clearRect(0, 0, W, H);
      const bg = ctx.createRadialGradient(this.cx, this.cy, 20, this.cx, this.cy, Math.max(W, H) / 1.5);
      bg.addColorStop(0, '#0d2137'); bg.addColorStop(1, '#06121f');
      ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
      if (this.showPressureField) this.drawPressureField();
      this.drawWaterFilm();
      this.drawCavitationRegions();
      this.drawBearing();
      for (const p of this.solver.particles) {
        const speed = Math.hypot(p.vx, p.vy);
        const size = 1.5 + speed * 0.05;
        ctx.globalAlpha = p.isInCavitation ? 0.4 : 0.9;
        ctx.beginPath();
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, size);
        grad.addColorStop(0, '#ffffff');
        grad.addColorStop(0.3, p.color);
        grad.addColorStop(1, 'rgba(0, 188, 212, 0)');
        ctx.fillStyle = grad;
        ctx.arc(p.x, p.y, size, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      if (this.showVectors) this.drawVelocityVectors();
      this.drawLegend();
    }
    drawPressureField() {
      const ctx = this.ctx, step = 6;
      for (let x = 0; x < this.canvas.clientWidth; x += step)
        for (let y = 0; y < this.canvas.clientHeight; y += step) {
          const dx = x - this.cx, dy = y - this.cy;
          const r = Math.hypot(dx, dy);
          if (r < this.R_inner || r > this.R_outer) continue;
          const theta = Math.atan2(dy, dx);
          const frac = (r - this.R_inner) / (this.R_outer - this.R_inner);
          const p = Math.exp(-Math.pow((theta - 0.5) / 0.8, 2)) * (1 - frac);
          ctx.fillStyle = `hsla(${240 - p * 180}, 100%, 50%, 0.18)`;
          ctx.fillRect(x, y, step, step);
        }
    }
    drawWaterFilm() {
      const ctx = this.ctx;
      ctx.beginPath();
      ctx.arc(this.cx, this.cy, this.R_outer, 0, Math.PI * 2);
      ctx.arc(this.cx, this.cy, this.R_inner, 0, Math.PI * 2, true);
      const filmGrad = ctx.createRadialGradient(this.cx, this.cy, this.R_inner, this.cx, this.cy, this.R_outer);
      filmGrad.addColorStop(0, 'rgba(0, 150, 200, 0.22)');
      filmGrad.addColorStop(0.5, 'rgba(0, 188, 212, 0.15)');
      filmGrad.addColorStop(1, 'rgba(0, 150, 200, 0.22)');
      ctx.fillStyle = filmGrad; ctx.fill();
      ctx.strokeStyle = 'rgba(0, 188, 212, 0.4)'; ctx.lineWidth = 1; ctx.stroke();
    }
    drawCavitationRegions() {
      const ctx = this.ctx;
      for (const r of this.solver.findCavitationRegions()) {
        ctx.beginPath(); ctx.arc(r.x, r.y, r.radius, 0, Math.PI * 2);
        const g = ctx.createRadialGradient(r.x, r.y, 0, r.x, r.y, r.radius);
        g.addColorStop(0, 'rgba(255, 200, 100, 0.55)');
        g.addColorStop(1, 'rgba(255, 100, 50, 0)');
        ctx.fillStyle = g; ctx.fill();
      }
    }
    drawBearing() {
      const ctx = this.ctx;
      ctx.beginPath(); ctx.arc(this.cx, this.cy, this.R_inner, 0, Math.PI * 2);
      ctx.strokeStyle = '#8d6e63'; ctx.lineWidth = 4; ctx.stroke();
      ctx.fillStyle = 'rgba(141, 110, 99, 0.35)'; ctx.fill();
      ctx.beginPath(); ctx.arc(this.cx, this.cy, this.R_outer, 0, Math.PI * 2);
      ctx.strokeStyle = '#5d4037'; ctx.lineWidth = 5; ctx.stroke();
      ctx.fillStyle = 'rgba(62, 39, 35, 0.2)'; ctx.fill();
      ctx.beginPath(); ctx.arc(this.cx, this.cy, 8, 0, Math.PI * 2);
      ctx.fillStyle = '#3e2723'; ctx.fill();
    }
    drawVelocityVectors() {
      const ctx = this.ctx;
      for (let i = 0; i < this.solver.particles.length; i += 5) {
        const p = this.solver.particles[i];
        ctx.beginPath(); ctx.moveTo(p.x, p.y);
        ctx.lineTo(p.x + p.vx * 2, p.y + p.vy * 2);
        ctx.strokeStyle = 'rgba(255,255,255,0.25)'; ctx.lineWidth = 0.5; ctx.stroke();
      }
    }
    drawLegend() {
      const ctx = this.ctx;
      const labels = [{ c: '#4fc3f7', t: '水' }, { c: '#ffb74d', t: '水汽' }, { c: '#5d4037', t: '壁面' }];
      labels.forEach((l, i) => {
        ctx.beginPath(); ctx.arc(14 + i * 60, 14, 5, 0, Math.PI * 2);
        ctx.fillStyle = l.c; ctx.fill();
        ctx.fillStyle = '#e0e0e0'; ctx.font = '11px sans-serif'; ctx.fillText(l.t, 24 + i * 60, 18);
      });
    }
    start() {
      const tick = () => {
        if (this.rpm > 0) for (let i = 0; i < 2; i++) this.solver.step();
        this.draw();
        this.animationId = requestAnimationFrame(tick);
      };
      tick();
    }
    stop() { if (this.animationId) cancelAnimationFrame(this.animationId); }
  }

  // ========== 3. 图表子系统 ==========
  class FlowCharts {
    constructor(canvasPowerId, canvasPressureId) {
      this.powerHistory = [];
      this.maxPoints = 60;
      this._initPowerChart(canvasPowerId);
      this._initPressureChart(canvasPressureId);
    }
    _initPowerChart(id) {
      const ctx = document.getElementById(id);
      if (!ctx) return;
      this.powerChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: [],
          datasets: [
            { label: '摩擦功耗(mW)', data: [], borderColor: '#ff5252', backgroundColor: 'rgba(255,82,82,0.1)', tension: 0.4, fill: true, yAxisID: 'y' },
            { label: '水膜厚度(μm)', data: [], borderColor: '#4fc3f7', backgroundColor: 'rgba(79,195,247,0.1)', tension: 0.4, fill: false, yAxisID: 'y1' },
            { label: '空化面积(%)', data: [], borderColor: '#ffb74d', backgroundColor: 'rgba(255,183,77,0.1)', tension: 0.4, fill: false, yAxisID: 'y2' },
          ],
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { labels: { color: '#e0e0e0' } },
            title: { display: true, text: '轴承状态趋势', color: '#fff', font: { size: 14 } },
          },
          scales: {
            x: { ticks: { color: '#aaa', maxRotation: 0 }, grid: { color: 'rgba(255,255,255,0.05)' } },
            y: { position: 'left', title: { display: true, text: 'mW', color: '#ff5252' }, ticks: { color: '#ff5252' }, grid: { color: 'rgba(255,255,255,0.05)' } },
            y1: { position: 'right', title: { display: true, text: 'μm', color: '#4fc3f7' }, ticks: { color: '#4fc3f7' }, grid: { drawOnChartArea: false } },
            y2: { display: false },
          },
        },
      });
    }
    _initPressureChart(id) {
      const ctx = document.getElementById(id);
      if (!ctx) return;
      this.pressureChart = new Chart(ctx, {
        type: 'line',
        data: { labels: Array.from({ length: 32 }, (_, i) => ((i / 32) * 360).toFixed(0) + '°'), datasets: [{
          label: '压力(Pa)', data: new Array(32).fill(0),
          borderColor: '#66bb6a', backgroundColor: 'rgba(102,187,106,0.2)',
          tension: 0.4, fill: true,
        }] },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          plugins: { legend: { labels: { color: '#e0e0e0' } }, title: { display: true, text: '周向压力分布', color: '#fff', font: { size: 14 } } },
          scales: {
            x: { ticks: { color: '#aaa', maxTicksLimit: 8 }, grid: { color: 'rgba(255,255,255,0.05)' }, title: { display: true, text: '周向角度', color: '#aaa' } },
            y: { beginAtZero: true, ticks: { color: '#aaa' }, grid: { color: 'rgba(255,255,255,0.05)' }, title: { display: true, text: 'Pa', color: '#aaa' } },
          },
        },
      });
    }
    addPowerData(timeLabel, powerMw, filmMicron, cavPct) {
      if (!this.powerChart) return;
      const d = this.powerChart.data;
      d.labels.push(timeLabel); d.labels = d.labels.slice(-this.maxPoints);
      d.datasets[0].data.push(powerMw); d.datasets[0].data = d.datasets[0].data.slice(-this.maxPoints);
      d.datasets[1].data.push(filmMicron); d.datasets[1].data = d.datasets[1].data.slice(-this.maxPoints);
      d.datasets[2].data.push(cavPct); d.datasets[2].data = d.datasets[2].data.slice(-this.maxPoints);
      this.powerChart.update('none');
    }
    updatePressureDistribution(pressureArray) {
      if (!this.pressureChart) return;
      this.pressureChart.data.datasets[0].data = pressureArray;
      this.pressureChart.update('none');
    }
  }

  // ========== 4. 面板集成 ==========
  class FlowPanel {
    constructor(opts) {
      this.particles = new WaterFilmParticles(opts.particlesCanvasId || 'flowParticlesCanvas', opts.particles || {});
      this.charts = new FlowCharts(opts.powerChartId || 'powerLossChart', opts.pressureChartId || 'pressureDistributionChart');
      this.rpm = 0;
      this.eccentricity = 0;
    }
    setRPM(r) { this.rpm = r; this.particles.setRPM(r); }
    setEccentricity(e) { this.eccentricity = e; this.particles.setEccentricity(e); }
    start() { this.particles.start(); }
    stop() { this.particles.stop(); }
    addPoint(label, powerMw, filmMicron, cavPct) { this.charts.addPowerData(label, powerMw, filmMicron, cavPct); }
    updatePressure(arr) { this.charts.updatePressureDistribution(arr); }
  }

  global.WaterFilmParticles = WaterFilmParticles;
  global.FlowCharts = FlowCharts;
  global.FlowPanel = FlowPanel;
  global._SPHSolver = SPHSolver;
  global._WendlandKernel = WendlandKernel;
})(window);
