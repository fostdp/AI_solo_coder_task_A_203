/**
 * main.js — 前端应用主控 v3.0
 * 适配：WaterBearing3D (三维) + FlowPanel (SPH+图表)
 */
(function () {
  'use strict';

  const BearingMonitoringApp = function (opts) {
    opts = opts || {};
    this.apiBase = opts.apiBase || window.location.origin;
    this.wsUrl = opts.wsUrl || (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws';
    this.currentBearing = opts.defaultBearing || 'bearing-south-01';
    this.ws = null;
    this.wsReconnectDelay = 3000;
    this.alerts = [];
    this.bearings = [];
    this.init();
  };

  BearingMonitoringApp.prototype.init = function () {
    this.init3D();
    this.initFlowPanel();
    this.initUI();
    this.loadBearings();
    this.connectWebSocket();
    this.bindEvents();
    this.startSimulationLoop();
  };

  BearingMonitoringApp.prototype.init3D = function () {
    try {
      this.bearing3d = new WaterBearing3D('bearing3d', {
        outerRadius: 5, clearance: 0.1, length: 8,
      });
    } catch (e) {
      console.error('3D 初始化失败', e);
    }
  };

  BearingMonitoringApp.prototype.initFlowPanel = function () {
    try {
      this.flowPanel = new FlowPanel({
        particlesCanvasId: 'particleCanvas',
        powerChartId: 'powerChart',
        pressureChartId: 'pressureChart',
        particles: { particleCount: 500 },
      });
      this.flowPanel.start();
    } catch (e) {
      console.error('FlowPanel 初始化失败', e);
    }
  };

  BearingMonitoringApp.prototype.initUI = function () {
    this.el = {
      bearingSelect: document.getElementById('bearingSelect'),
      liveRpm: document.getElementById('liveRpm'),
      livePressure: document.getElementById('livePressure'),
      liveTemp: document.getElementById('liveTemp'),
      liveFc: document.getElementById('liveFriction'),
      livePower: document.getElementById('livePower'),
      liveFilmStatus: document.getElementById('liveFilm'),
      livePowerStatus: document.getElementById('resultRupture'),
      alertsList: document.getElementById('alertList'),
      alertBanner: document.getElementById('alertBanner'),
      simBtn: document.getElementById('runSimulation'),
      simRpm: document.getElementById('simRpm'),
      simEcc: document.getElementById('simEccentricity'),
      simTemp: document.getElementById('simTemp'),
      simResult: document.getElementById('resultCavitation'),
    };
  };

  BearingMonitoringApp.prototype.bindEvents = function () {
    if (this.el.bearingSelect) {
      this.el.bearingSelect.addEventListener('change', (e) => {
        this.currentBearing = e.target.value;
        this.loadLatestData();
      });
    }
    if (this.el.simBtn) {
      this.el.simBtn.addEventListener('click', () => this.runSimulation());
    }
  };

  BearingMonitoringApp.prototype.loadBearings = async function () {
    try {
      const r = await fetch(this.apiBase + '/api/bearings');
      this.bearings = await r.json() || [];
      if (this.el.bearingSelect) {
        this.el.bearingSelect.innerHTML = this.bearings
          .map(b => `<option value="${b.id}">${b.name} (${b.location})</option>`)
          .join('');
        if (this.bearings.find(b => b.id === this.currentBearing)) {
          this.el.bearingSelect.value = this.currentBearing;
        }
      }
    } catch (e) { console.error(e); }
  };

  BearingMonitoringApp.prototype.loadLatestData = async function () {
    try {
      const r = await fetch(this.apiBase + '/api/bearing/' + this.currentBearing + '/latest');
      if (r.ok) {
        const data = await r.json();
        this.updateLiveData(data);
      }
    } catch (e) { console.error(e); }
  };

  BearingMonitoringApp.prototype.connectWebSocket = function () {
    try {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.onopen = () => console.log('[WS] 已连接');
      this.ws.onclose = () => {
        console.log('[WS] 断开，重连中…');
        setTimeout(() => this.connectWebSocket(), this.wsReconnectDelay);
      };
      this.ws.onerror = (e) => console.error('[WS] 错误', e);
      this.ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'bearing_data' || msg.data && msg.data.bearing_id) {
            this.handleBearingData(msg.data || msg);
          } else if (msg.type === 'alert' || msg.severity) {
            this.handleAlert(msg.data || msg);
          }
        } catch (e) { console.error(e); }
      };
    } catch (e) { console.error('WS 连接失败', e); }
  };

  BearingMonitoringApp.prototype.handleBearingData = function (d) {
    if (!d) return;
    this.updateLiveData(d);
    const label = new Date(d.timestamp || Date.now()).toLocaleTimeString();
    if (this.flowPanel) {
      this.flowPanel.addPoint(label, (d.power_loss_watts || 0) * 1000,
        (d.min_film_thickness_micron != null ? d.min_film_thickness_micron : 80),
        (d.cavitation_area_fraction || 0) * 100);
    }
    if (this.bearing3d) {
      this.bearing3d.setRPM(d.rpm || 0);
      this.bearing3d.setEccentricity(d.eccentricity_ratio || 0);
      this.bearing3d.setWaterPressure(d.water_pressure || 0);
      this.bearing3d.setWaterTemperature(d.water_temperature || 20);
    }
    if (this.flowPanel) {
      this.flowPanel.setRPM(d.rpm || 0);
      this.flowPanel.setEccentricity(d.eccentricity_ratio || 0);
    }
  };

  BearingMonitoringApp.prototype.handleAlert = function (a) {
    if (!a) return;
    this.alerts.unshift(a);
    if (this.alerts.length > 50) this.alerts.pop();
    this.renderAlerts();
    this.showAlertBanner(a);
  };

  BearingMonitoringApp.prototype.updateLiveData = function (d) {
    const set = (el, v, suf) => { if (el && v != null) el.textContent = Number(v).toFixed(typeof v === 'number' && Math.abs(v) < 1 ? 4 : 2) + (suf || ''); };
    set(this.el.liveRpm, d.rpm);
    set(this.el.livePressure, d.water_pressure, ' kPa');
    set(this.el.liveTemp, d.water_temperature, ' °C');
    set(this.el.liveFc, d.friction_coefficient);
    set(this.el.livePower, (d.power_loss_watts || 0) * 1000, ' mW');
    if (this.el.liveFilmStatus) {
      this.el.liveFilmStatus.textContent = d.film_status || 'normal';
      this.el.liveFilmStatus.className = 'status status-' + (d.film_status || 'normal');
    }
    if (this.el.livePowerStatus) {
      this.el.livePowerStatus.textContent = d.power_status || 'normal';
      this.el.livePowerStatus.className = 'status status-' + (d.power_status || 'normal');
    }
  };

  BearingMonitoringApp.prototype.renderAlerts = function () {
    if (!this.el.alertsList) return;
    this.el.alertsList.innerHTML = this.alerts.slice(0, 20).map(a => `
      <div class="alert-item alert-${a.severity || 'info'}">
        <span class="alert-type">${a.type || 'alert'}</span>
        <span class="alert-msg">${a.message || ''}</span>
        <span class="alert-time">${new Date(a.timestamp || Date.now()).toLocaleString()}</span>
      </div>`).join('') || '<div class="alert-empty">暂无告警</div>';
  };

  BearingMonitoringApp.prototype.showAlertBanner = function (a) {
    if (!this.el.alertBanner) return;
    const sev = a.severity || 'warning';
    this.el.alertBanner.className = 'alert-banner alert-banner-' + sev;
    this.el.alertBanner.innerHTML = `⚠️ [${a.type || sev}] ${a.message || ''} <span class="alert-close">×</span>`;
    this.el.alertBanner.style.display = 'block';
    const closeBtn = this.el.alertBanner.querySelector('.alert-close');
    if (closeBtn) closeBtn.onclick = () => { this.el.alertBanner.style.display = 'none'; };
    setTimeout(() => { if (this.el.alertBanner) this.el.alertBanner.style.display = 'none'; }, 8000);
  };

  BearingMonitoringApp.prototype.runSimulation = async function () {
    const body = {
      rpm: Number(this.el.simRpm?.value || 30),
      eccentricity_ratio: Number(this.el.simEcc?.value || 0.3),
      load_n: 800,
      temperature: (this.el.simTemp ? Number(this.el.simTemp.value) + 273.15 : 293.15),
      bearing_id: this.currentBearing,
      viscosity_model: 'andrade',
    };
    if (this.el.simBtn) { this.el.simBtn.disabled = true; this.el.simBtn.textContent = '计算中…'; }
    try {
      const r = await fetch(this.apiBase + '/api/simulation/calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (this.el.simResult) {
        this.el.simResult.style.display = 'block';
        this.el.simResult.textContent = (d.cavitation_area_fraction * 100).toFixed(2) + '% / ' + (d.film_status || '');
      }
      const rup = document.getElementById('resultRupture');
      if (rup) rup.textContent = d.film_status || '';
      const maxP = document.getElementById('resultMaxPressure');
      if (maxP) maxP.textContent = (d.max_pressure_pa / 1000).toFixed(1) + ' kPa';
      const load = document.getElementById('resultLoadCapacity');
      if (load) load.textContent = d.load_capacity?.toFixed(1) + ' N';
      if (this.flowPanel) this.flowPanel.updatePressure(d.pressure_distribution || []);
      this.handleBearingData({
        rpm: d.rpm, eccentricity_ratio: body.eccentricity_ratio,
        power_loss_watts: d.power_loss_watts, water_pressure: (d.max_pressure_pa || 0) / 1000,
        water_temperature: (d.temperature_inlet_k || 293.15) - 273.15,
        friction_coefficient: d.friction_coefficient,
        min_film_thickness_micron: (d.min_film_thickness_m || 0) * 1e6,
        cavitation_area_fraction: d.cavitation_area_fraction,
        film_status: d.film_status, power_status: d.power_status,
        timestamp: new Date().toISOString(),
      });
    } catch (e) {
      console.error(e);
      if (this.el.simResult) this.el.simResult.textContent = '失败';
    } finally {
      if (this.el.simBtn) { this.el.simBtn.disabled = false; this.el.simBtn.textContent = '运行仿真'; }
    }
  };

  BearingMonitoringApp.prototype._formatSimResult = function (d) {
    const kv = [
      ['承载力(N)', d.load_capacity?.toFixed(1)],
      ['最大压力(Pa)', d.max_pressure_pa?.toFixed(0)],
      ['最小膜厚(μm)', (d.min_film_thickness_m * 1e6).toFixed(2)],
      ['摩擦系数', d.friction_coefficient?.toFixed(5)],
      ['摩擦扭矩(N·m)', d.friction_torque_nm?.toFixed(4)],
      ['功耗(mW)', (d.power_loss_watts * 1000).toFixed(2)],
      ['流量(m³/s)', d.flow_rate_m3s?.toExponential(2)],
      ['空化比例(%)', (d.cavitation_area_fraction * 100).toFixed(2)],
      ['进口温度(K)', d.temperature_inlet_k?.toFixed(1)],
      ['出口温度(K)', d.temperature_outlet_k?.toFixed(1)],
      ['水膜状态', d.film_status],
      ['功耗状态', d.power_status],
      ['求解收敛', d.solver_converged ? '是 (' + d.solver_iterations + '步)' : '否'],
    ];
    return `<h4>仿真结果</h4><table class="sim-table"><tbody>${
      kv.map(([k, v]) => `<tr><td>${k}</td><td><b>${v}</b></td></tr>`).join('')
    }</tbody></table>${d.alerts_generated ? `<p class="alert-warning">本次仿真触发 ${d.alerts_generated} 条告警</p>` : ''}`;
  };

  BearingMonitoringApp.prototype.startSimulationLoop = function () {
    setInterval(() => this.loadLatestData(), 5000);
  };

  window.BearingMonitoringApp = BearingMonitoringApp;
  document.addEventListener('DOMContentLoaded', function () {
    window.app = new BearingMonitoringApp();
  });
})();
