class BearingMonitoringApp {
    constructor() {
        this.bearing3d = null;
        this.particles = null;
        this.charts = null;
        this.ws = null;
        this.currentBearing = 'bearing_001';
        this.alerts = [];
        this.currentTimeRange = '-1h';

        this.init();
    }

    init() {
        this.bearing3d = new Bearing3D('bearing3d');
        this.particles = new WaterFilmParticles('particleCanvas');
        this.charts = new BearingCharts();
        this.charts.init();

        this.bindEvents();
        this.connectWebSocket();
        this.loadLatestData();
        this.loadAlerts();
    }

    bindEvents() {
        document.getElementById('bearingSelect').addEventListener('change', (e) => {
            this.currentBearing = e.target.value;
            this.loadLatestData();
            this.loadHistoryData();
            this.loadAlerts();
        });

        document.getElementById('showParticles').addEventListener('change', (e) => {
            this.bearing3d.setShowParticles(e.target.checked);
        });

        document.getElementById('showWireframe').addEventListener('change', (e) => {
            this.bearing3d.setWireframe(e.target.checked);
        });

        document.getElementById('rotSpeed').addEventListener('input', (e) => {
            this.bearing3d.setRotationSpeed(parseFloat(e.target.value));
        });

        document.getElementById('simRpm').addEventListener('input', (e) => {
            const val = parseFloat(e.target.value);
            document.getElementById('simRpmValue').textContent = val.toFixed(0);
            this.bearing3d.setRotationSpeed(val);
            this.particles.setRpm(val);
        });

        document.getElementById('simEccentricity').addEventListener('input', (e) => {
            const val = parseFloat(e.target.value);
            document.getElementById('simEccentricityValue').textContent = val.toFixed(2);
            this.bearing3d.setEccentricity(val);
            this.particles.setEccentricity(val);
            document.getElementById('eccentricityDisplay').textContent = val.toFixed(2);

            const clearance = 200;
            const filmThickness = clearance * (1 - val);
            document.getElementById('filmThicknessDisplay').textContent = filmThickness.toFixed(0) + ' μm';
        });

        document.getElementById('simTemp').addEventListener('input', (e) => {
            const val = parseFloat(e.target.value);
            document.getElementById('simTempValue').textContent = val.toFixed(1);
        });

        document.getElementById('runSimulation').addEventListener('click', () => {
            this.runSimulation();
        });

        document.getElementById('particleCount').addEventListener('input', (e) => {
            this.particles.setParticleCount(parseInt(e.target.value));
        });

        document.getElementById('particleSpeed').addEventListener('input', (e) => {
            this.particles.setSpeed(parseFloat(e.target.value));
        });

        document.querySelectorAll('.time-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const range = e.target.dataset.range;
                this.currentTimeRange = range;
                this.charts.setTimeRange(range);
                this.loadHistoryData();
            });
        });
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.updateConnectionStatus(false, '连接中...');

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                console.log('WebSocket 连接已建立');
                this.updateConnectionStatus(true, '已连接');
            };

            this.ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    this.handleWebSocketMessage(msg);
                } catch (e) {
                    console.error('解析 WebSocket 消息失败:', e);
                }
            };

            this.ws.onclose = () => {
                console.log('WebSocket 连接已关闭');
                this.updateConnectionStatus(false, '已断开');
                setTimeout(() => this.connectWebSocket(), 3000);
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket 错误:', error);
                this.updateConnectionStatus(false, '连接错误');
            };
        } catch (e) {
            console.error('创建 WebSocket 失败:', e);
            setTimeout(() => this.connectWebSocket(), 5000);
        }
    }

    handleWebSocketMessage(msg) {
        switch (msg.type) {
            case 'connected':
                console.log(msg.message);
                break;

            case 'bearing_data':
                this.handleBearingData(msg.data);
                break;

            case 'alert':
                this.handleAlert(msg.data);
                break;

            case 'pong':
                break;
        }
    }

    handleBearingData(data) {
        if (data.bearing_id !== this.currentBearing) return;

        this.updateLiveData(data);

        const timestamp = data.timestamp || data.received_at || new Date().toISOString();
        this.charts.addPowerDataPoint(
            timestamp,
            data.power_loss || 0,
            data.water_temperature || 0
        );

        if (data.eccentricity_ratio !== undefined) {
            this.bearing3d.setEccentricity(data.eccentricity_ratio);
            this.particles.setEccentricity(data.eccentricity_ratio);
        }
        if (data.rpm !== undefined) {
            this.bearing3d.setRotationSpeed(data.rpm * 0.8);
            this.particles.setRpm(data.rpm);
        }

        this.updateFilmStatusBadge(data.film_status || 'normal');
    }

    handleAlert(alertData) {
        this.alerts.unshift(alertData);
        if (this.alerts.length > 50) this.alerts.pop();

        this.renderAlerts();
        this.showAlertBanner(alertData);

        document.getElementById('alertCount').textContent = this.alerts.length;
    }

    updateLiveData(data) {
        document.getElementById('liveRpm').textContent =
            data.rpm ? data.rpm.toFixed(1) : '--';

        document.getElementById('livePressure').textContent =
            data.water_pressure ? (data.water_pressure / 1000).toFixed(1) : '--';

        document.getElementById('liveFriction').textContent =
            data.friction_coefficient ? data.friction_coefficient.toFixed(6) : '--';

        document.getElementById('liveTemp').textContent =
            data.water_temperature ? data.water_temperature.toFixed(1) : '--';

        document.getElementById('livePower').textContent =
            data.power_loss ? data.power_loss.toFixed(2) : '--';

        document.getElementById('liveFilm').textContent =
            data.min_film_thickness ? (data.min_film_thickness * 1e6).toFixed(1) : '--';
    }

    updateFilmStatusBadge(status) {
        const badge = document.getElementById('filmStatusBadge');
        badge.className = 'badge';

        switch (status) {
            case 'ruptured':
                badge.classList.add('badge-critical');
                badge.textContent = '破裂';
                break;
            case 'warning':
                badge.classList.add('badge-warning');
                badge.textContent = '警告';
                break;
            default:
                badge.classList.add('badge-normal');
                badge.textContent = '正常';
        }
    }

    updateConnectionStatus(connected, text) {
        const dot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');

        if (connected) {
            dot.classList.add('connected');
        } else {
            dot.classList.remove('connected');
        }
        statusText.textContent = text;
    }

    showAlertBanner(alert) {
        const banner = document.getElementById('alertBanner');
        const message = document.getElementById('alertMessage');

        message.textContent = alert.message;
        banner.style.display = 'flex';

        banner.className = 'alert-banner';
        if (alert.severity === 'critical') {
            banner.style.background = 'linear-gradient(90deg, rgba(244, 67, 54, 0.3) 0%, rgba(244, 67, 54, 0.1) 100%)';
        } else {
            banner.style.background = 'linear-gradient(90deg, rgba(255, 152, 0, 0.3) 0%, rgba(255, 152, 0, 0.1) 100%)';
        }

        setTimeout(() => {
            banner.style.display = 'none';
        }, 8000);
    }

    renderAlerts() {
        const container = document.getElementById('alertList');

        if (this.alerts.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无告警记录</div>';
            return;
        }

        let html = '';
        for (const alert of this.alerts.slice(0, 20)) {
            const time = new Date(alert.timestamp).toLocaleString('zh-CN');
            const icon = alert.severity === 'critical' ? '🚨' : '⚠️';
            const severityClass = alert.severity === 'critical' ? 'critical' : 'warning';

            html += `
                <div class="alert-item ${severityClass}">
                    <div class="alert-item-icon">${icon}</div>
                    <div class="alert-item-content">
                        <div class="alert-item-title">${alert.message}</div>
                        <div class="alert-item-desc">轴承: ${alert.bearing_id} · 类型: ${alert.alert_type}</div>
                        <div class="alert-item-time">${time}</div>
                    </div>
                </div>
            `;
        }

        container.innerHTML = html;
    }

    async loadLatestData() {
        try {
            const response = await fetch(`/api/bearing/${this.currentBearing}/latest`);
            if (response.ok) {
                const result = await response.json();
                if (result.data) {
                    this.updateLiveData(result.data);
                    this.updateFilmStatusBadge(result.data.film_status || 'normal');
                }
            }
        } catch (e) {
            console.error('加载最新数据失败:', e);
        }
    }

    async loadHistoryData() {
        try {
            const response = await fetch(
                `/api/bearing/${this.currentBearing}/history?start_time=${this.currentTimeRange}`
            );
            if (response.ok) {
                const result = await response.json();
                this.charts.updateHistoryData(result.data || []);
            }
        } catch (e) {
            console.error('加载历史数据失败:', e);
        }
    }

    async loadAlerts() {
        try {
            const response = await fetch(`/api/alerts?bearing_id=${this.currentBearing}&limit=20`);
            if (response.ok) {
                const result = await response.json();
                this.alerts = result.alerts || [];
                this.renderAlerts();
                document.getElementById('alertCount').textContent = this.alerts.length;
            }
        } catch (e) {
            console.error('加载告警记录失败:', e);
        }
    }

    async runSimulation() {
        const rpm = parseFloat(document.getElementById('simRpm').value);
        const eccentricity = parseFloat(document.getElementById('simEccentricity').value);
        const temperature = parseFloat(document.getElementById('simTemp').value);

        const btn = document.getElementById('runSimulation');
        btn.textContent = '计算中...';
        btn.disabled = true;

        try {
            const response = await fetch('/api/simulation/calculate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    rpm: rpm,
                    eccentricity_ratio: eccentricity,
                    water_temperature: temperature,
                }),
            });

            if (response.ok) {
                const result = await response.json();
                this.updateSimulationResults(result);
                this.charts.updatePressureDistribution(
                    result.theta,
                    result.pressure_distribution,
                    result.film_thickness
                );
            } else {
                console.error('仿真计算失败');
            }
        } catch (e) {
            console.error('仿真计算出错:', e);
        } finally {
            btn.textContent = '运行仿真';
            btn.disabled = false;
        }
    }

    updateSimulationResults(result) {
        document.getElementById('resultMaxPressure').textContent =
            (result.max_pressure / 1000).toFixed(1) + ' kPa';
        document.getElementById('resultLoadCapacity').textContent =
            result.load_capacity.toFixed(1) + ' N';
        document.getElementById('resultCavitation').textContent =
            (result.cavitation_area_fraction * 100).toFixed(1) + ' %';
        document.getElementById('resultRupture').textContent =
            (result.rupture_risk * 100).toFixed(1) + ' %';

        this.updateFilmStatusBadge(result.film_status);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.app = new BearingMonitoringApp();
});
