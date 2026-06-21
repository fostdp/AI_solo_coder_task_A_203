class WaterFilmParticles {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.particles = [];
        this.particleCount = 500;
        this.speedFactor = 0.5;
        this.rpm = 35;
        this.eccentricity = 0.3;
        this.cavitationAreas = [];
        this.pressureField = [];
        this.filmThickness = [];
        this.theta = [];
        this.animationId = null;
        this.time = 0;

        this.bearingRadius = 120;
        this.clearance = 20;
        this.centerX = 0;
        this.centerY = 0;

        this.init();
    }

    init() {
        this.resize();
        window.addEventListener('resize', () => this.resize());
        this.initParticles();
        this.generatePressureField();
        this.animate();
    }

    resize() {
        const rect = this.canvas.getBoundingClientRect();
        this.canvas.width = rect.width * window.devicePixelRatio;
        this.canvas.height = rect.height * window.devicePixelRatio;
        this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

        this.width = rect.width;
        this.height = rect.height;
        this.centerX = this.width / 2;
        this.centerY = this.height / 2;

        const scale = Math.min(this.width, this.height) / 300;
        this.bearingRadius = 100 * scale;
        this.clearance = 18 * scale;

        if (this.particles.length > 0) {
            this.initParticles();
        }
    }

    initParticles() {
        this.particles = [];
        for (let i = 0; i < this.particleCount; i++) {
            const angle = Math.random() * Math.PI * 2;
            const t = Math.random();
            const radius = this.bearingRadius + this.clearance * (0.1 + t * 0.8);

            this.particles.push({
                x: this.centerX + Math.cos(angle) * radius,
                y: this.centerY + Math.sin(angle) * radius,
                angle: angle,
                radius: radius,
                speed: 0.5 + Math.random() * 0.5,
                size: 1.5 + Math.random() * 2,
                alpha: 0.3 + Math.random() * 0.5,
                zPhase: Math.random() * Math.PI * 2,
                zSpeed: 0.01 + Math.random() * 0.02,
            });
        }
    }

    generatePressureField() {
        const n = 64;
        this.theta = [];
        this.pressureField = [];
        this.filmThickness = [];

        for (let i = 0; i < n; i++) {
            const angle = (i / n) * Math.PI * 2;
            this.theta.push(angle);

            const e = this.eccentricity;
            const h = 1 + e * Math.cos(angle);
            this.filmThickness.push(h);

            let pressure;
            if (Math.abs(angle) < Math.PI * 0.7) {
                pressure = Math.exp(-Math.pow((angle - 0.5) / 0.8, 2)) * 0.8;
                pressure += Math.exp(-Math.pow((angle + 0.3) / 0.6, 2)) * 0.5;
            } else {
                pressure = -0.3;
            }

            this.pressureField.push(Math.max(0, pressure));
        }

        this.cavitationAreas = [];
        let inCavitation = false;
        let startAngle = 0;

        for (let i = 0; i < n; i++) {
            if (this.pressureField[i] < 0.05 && !inCavitation) {
                inCavitation = true;
                startAngle = this.theta[i];
            } else if (this.pressureField[i] >= 0.05 && inCavitation) {
                inCavitation = false;
                this.cavitationAreas.push({
                    start: startAngle,
                    end: this.theta[i],
                });
            }
        }
    }

    setParticleCount(count) {
        this.particleCount = count;
        this.initParticles();
    }

    setSpeed(speed) {
        this.speedFactor = speed / 50;
    }

    setRpm(rpm) {
        this.rpm = rpm;
    }

    setEccentricity(ecc) {
        this.eccentricity = ecc;
        this.generatePressureField();
    }

    updateParticles() {
        const omega = this.rpm * 2 * Math.PI / 60;
        const baseSpeed = omega * 0.01 * this.speedFactor;

        for (const p of this.particles) {
            const dx = p.x - this.centerX;
            const dy = p.y - this.centerY;
            const dist = Math.sqrt(dx * dx + dy * dy);
            const angle = Math.atan2(dy, dx);

            const normRadius = (dist - this.bearingRadius) / this.clearance;

            const profileSpeed = normRadius * (2 - normRadius);

            const angleIdx = Math.floor(((angle + Math.PI * 2) % (Math.PI * 2)) /
                (Math.PI * 2) * this.theta.length);
            const pressure = this.pressureField[Math.min(angleIdx, this.pressureField.length - 1)] || 0;

            const pressureGradient = pressure * 0.05;

            p.angle += baseSpeed * profileSpeed + pressureGradient;

            const zOffset = Math.sin(this.time * p.zSpeed + p.zPhase) * 2;

            const wobble = Math.sin(this.time * 0.03 + p.angle * 3) * 1.5;
            const newRadius = dist + wobble * 0.1;

            const minR = this.bearingRadius + 2;
            const maxR = this.bearingRadius + this.clearance - 2;
            const clampedRadius = Math.max(minR, Math.min(maxR, newRadius));

            const eccOffset = this.eccentricity * this.clearance * 0.5;

            p.x = this.centerX + Math.cos(p.angle) * clampedRadius + eccOffset * Math.cos(p.angle);
            p.y = this.centerY + Math.sin(p.angle) * clampedRadius + eccOffset * Math.sin(p.angle);

            p.alpha = 0.2 + profileSpeed * 0.6;

            if (this._isInCavitation(p.angle)) {
                p.alpha *= 0.4;
                p.size = p.size * 1.2;
            }
        }
    }

    _isInCavitation(angle) {
        const normAngle = (angle + Math.PI * 2) % (Math.PI * 2);
        for (const area of this.cavitationAreas) {
            let start = (area.start + Math.PI * 2) % (Math.PI * 2);
            let end = (area.end + Math.PI * 2) % (Math.PI * 2);

            if (start > end) {
                if (normAngle >= start || normAngle <= end) return true;
            } else {
                if (normAngle >= start && normAngle <= end) return true;
            }
        }
        return false;
    }

    drawBackground() {
        this.ctx.clearRect(0, 0, this.width, this.height);

        const gradient = this.ctx.createRadialGradient(
            this.centerX, this.centerY, this.bearingRadius * 0.5,
            this.centerX, this.centerY, this.bearingRadius + this.clearance * 2
        );
        gradient.addColorStop(0, 'rgba(30, 80, 130, 0.3)');
        gradient.addColorStop(1, 'rgba(10, 30, 60, 0.1)');
        this.ctx.fillStyle = gradient;
        this.ctx.fillRect(0, 0, this.width, this.height);
    }

    drawBearing() {
        const outerRadius = this.bearingRadius + this.clearance + 15;
        const outerGrad = this.ctx.createRadialGradient(
            this.centerX, this.centerY, this.bearingRadius + this.clearance,
            this.centerX, this.centerY, outerRadius
        );
        outerGrad.addColorStop(0, '#8d6e63');
        outerGrad.addColorStop(1, '#5d4037');

        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, outerRadius, 0, Math.PI * 2);
        this.ctx.fillStyle = outerGrad;
        this.ctx.fill();

        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, this.bearingRadius + this.clearance, 0, Math.PI * 2);
        this.ctx.strokeStyle = '#6d4c41';
        this.ctx.lineWidth = 2;
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, this.bearingRadius - 10, 0, Math.PI * 2);
        this.ctx.fillStyle = '#a1887f';
        this.ctx.fill();

        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, this.bearingRadius - 10, 0, Math.PI * 2);
        this.ctx.strokeStyle = '#8d6e63';
        this.ctx.lineWidth = 2;
        this.ctx.stroke();

        const eccOffset = this.eccentricity * this.clearance * 0.5;

        this.ctx.beginPath();
        this.ctx.arc(this.centerX + eccOffset, this.centerY, this.bearingRadius, 0, Math.PI * 2);
        this.ctx.strokeStyle = '#bcaaa4';
        this.ctx.lineWidth = 3;
        this.ctx.stroke();
    }

    drawWaterFilm() {
        const eccOffset = this.eccentricity * this.clearance * 0.5;

        this.ctx.save();

        const filmGradient = this.ctx.createRadialGradient(
            this.centerX + eccOffset, this.centerY, this.bearingRadius,
            this.centerX, this.centerY, this.bearingRadius + this.clearance
        );
        filmGradient.addColorStop(0, 'rgba(129, 212, 250, 0.4)');
        filmGradient.addColorStop(0.5, 'rgba(79, 195, 247, 0.3)');
        filmGradient.addColorStop(1, 'rgba(41, 182, 246, 0.2)');

        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, this.bearingRadius + this.clearance, 0, Math.PI * 2);
        this.ctx.arc(this.centerX + eccOffset, this.centerY, this.bearingRadius, 0, Math.PI * 2, true);
        this.ctx.fillStyle = filmGradient;
        this.ctx.fill('evenodd');

        this.ctx.restore();
    }

    drawCavitation() {
        for (const area of this.cavitationAreas) {
            this.ctx.save();

            const cavGradient = this.ctx.createRadialGradient(
                this.centerX, this.centerY, this.bearingRadius,
                this.centerX, this.centerY, this.bearingRadius + this.clearance
            );
            cavGradient.addColorStop(0, 'rgba(255, 255, 255, 0.1)');
            cavGradient.addColorStop(0.5, 'rgba(255, 255, 255, 0.2)');
            cavGradient.addColorStop(1, 'rgba(255, 255, 255, 0.05)');

            this.ctx.beginPath();
            this.ctx.arc(this.centerX, this.centerY, this.bearingRadius + this.clearance,
                area.start, area.end);
            this.ctx.arc(this.centerX, this.centerY, this.bearingRadius,
                area.end, area.start, true);
            this.ctx.fillStyle = cavGradient;
            this.ctx.fill();

            for (let i = 0; i < 5; i++) {
                const angle = area.start + Math.random() * (area.end - area.start);
                const r = this.bearingRadius + Math.random() * this.clearance * 0.8;
                const size = 2 + Math.random() * 4;

                this.ctx.beginPath();
                this.ctx.arc(
                    this.centerX + Math.cos(angle) * r,
                    this.centerY + Math.sin(angle) * r,
                    size,
                    0, Math.PI * 2
                );
                this.ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
                this.ctx.fill();
            }

            this.ctx.restore();
        }
    }

    drawPressureIndicator() {
        const barWidth = 120;
        const barHeight = 8;
        const barX = 20;
        const barY = 20;

        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
        this.ctx.fillRect(barX, barY, barWidth, barHeight);

        const maxPressure = Math.max(...this.pressureField);
        for (let i = 0; i < barWidth; i++) {
            const t = i / barWidth;
            const pressure = Math.sin(t * Math.PI) * maxPressure;
            const hue = 200 - pressure * 180;
            this.ctx.fillStyle = `hsla(${hue}, 80%, 60%, 0.8)`;
            this.ctx.fillRect(barX + i, barY, 1, barHeight);
        }

        this.ctx.fillStyle = '#90a4ae';
        this.ctx.font = '12px sans-serif';
        this.ctx.fillText('压力分布', barX, barY - 5);
        this.ctx.fillText('低', barX, barY + barHeight + 15);
        this.ctx.fillText('高', barX + barWidth - 20, barY + barHeight + 15);
    }

    drawParticles() {
        for (const p of this.particles) {
            const gradient = this.ctx.createRadialGradient(
                p.x, p.y, 0,
                p.x, p.y, p.size * 2
            );
            gradient.addColorStop(0, `rgba(179, 229, 252, ${p.alpha})`);
            gradient.addColorStop(1, 'rgba(79, 195, 247, 0)');

            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.size * 2, 0, Math.PI * 2);
            this.ctx.fillStyle = gradient;
            this.ctx.fill();

            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.size * 0.5, 0, Math.PI * 2);
            this.ctx.fillStyle = `rgba(255, 255, 255, ${p.alpha * 0.8})`;
            this.ctx.fill();
        }
    }

    drawLabels() {
        this.ctx.fillStyle = '#78909c';
        this.ctx.font = '12px sans-serif';
        this.ctx.fillText('水膜流场粒子仿真', 20, this.height - 15);

        const infoY = 50;
        this.ctx.fillStyle = '#90a4ae';
        this.ctx.font = '11px sans-serif';
        this.ctx.fillText(`粒子数: ${this.particleCount}`, 20, infoY + 20);
        this.ctx.fillText(`转速: ${this.rpm} RPM`, 20, infoY + 38);
        this.ctx.fillText(`偏心率: ${this.eccentricity.toFixed(2)}`, 20, infoY + 56);
    }

    animate() {
        this.animationId = requestAnimationFrame(() => this.animate());
        this.time++;

        this.updateParticles();

        this.drawBackground();
        this.drawBearing();
        this.drawWaterFilm();
        this.drawCavitation();
        this.drawParticles();
        this.drawPressureIndicator();
        this.drawLabels();
    }

    destroy() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
        }
    }
}
