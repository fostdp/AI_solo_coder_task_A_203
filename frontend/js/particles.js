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
        if (r > this.h || r < 1e-6) return { x: 0, y: 0 };
        const q = r / this.h;
        const term = (1 - q / 2);
        const factor = this.alpha * (-5 * q / this.h) * term * term * term;
        return {
            x: factor * x / r,
            y: factor * y / r
        };
    }

    laplacian(r) {
        if (r > this.h) return 0;
        const q = r / this.h;
        const term = 1 - q / 2;
        return this.alpha * (15 / this.h2) * q * term * term;
    }
}

class SPHParticle {
    constructor(x, y) {
        this.x = x;
        this.y = y;
        this.vx = 0;
        this.vy = 0;
        this.ax = 0;
        this.ay = 0;
        this.density = 0;
        this.pressure = 0;
        this.mass = 1.0;
        this.color = { r: 100, g: 200, b: 255 };
        this.phase = Math.random() * Math.PI * 2;
        this.isInCavitation = false;
    }
}

class SPHSolver {
    constructor(config) {
        this.particles = [];
        this.kernel = new WendlandKernel(config.kernelRadius || 15);
        this.restDensity = config.restDensity || 1000;
        this.gasConstant = config.gasConstant || 200;
        this.viscosity = config.viscosity || 1.5;
        this.damping = config.damping || 0.998;
        this.dt = config.dt || 0.016;
        this.gravity = config.gravity || 0;

        this.boundaryInner = config.boundaryInner || 100;
        this.boundaryOuter = config.boundaryOuter || 120;
        this.centerX = config.centerX || 0;
        this.centerY = config.centerY || 0;
        this.eccentricity = config.eccentricity || 0;
        this.eccentricityX = 0;

        this.omega = config.omega || 0.5;
        this.boundaryRestitution = config.boundaryRestitution || 0.3;
        this.boundaryForce = config.boundaryForce || 5000;

        this.pressureField = [];
        this.cavitationRegions = [];
        this.cellSize = this.kernel.h;
        this.cells = new Map();
    }

    addParticle(x, y) {
        this.particles.push(new SPHParticle(x, y));
    }

    clearParticles() {
        this.particles = [];
    }

    setParticleCount(count) {
        const currentCount = this.particles.length;
        if (count > currentCount) {
            for (let i = currentCount; i < count; i++) {
                const angle = Math.random() * Math.PI * 2;
                const t = Math.random();
                const radius = this.boundaryInner + 2 + t * (this.boundaryOuter - this.boundaryInner - 4);
                const eccOff = this.eccentricityX * Math.cos(angle);
                const x = this.centerX + Math.cos(angle) * radius + eccOff;
                const y = this.centerY + Math.sin(angle) * radius;
                this.addParticle(x, y);
            }
        } else if (count < currentCount) {
            this.particles.splice(count);
        }
    }

    buildNeighborList() {
        this.cells.clear();
        const invCellSize = 1 / this.cellSize;

        for (let i = 0; i < this.particles.length; i++) {
            const p = this.particles[i];
            const cx = Math.floor(p.x * invCellSize);
            const cy = Math.floor(p.y * invCellSize);
            const key = cx + '_' + cy;
            if (!this.cells.has(key)) {
                this.cells.set(key, []);
            }
            this.cells.get(key).push(i);
        }
    }

    getNeighbors(particleIndex) {
        const neighbors = [];
        const p = this.particles[particleIndex];
        const invCellSize = 1 / this.cellSize;
        const cx = Math.floor(p.x * invCellSize);
        const cy = Math.floor(p.y * invCellSize);

        for (let dx = -1; dx <= 1; dx++) {
            for (let dy = -1; dy <= 1; dy++) {
                const key = (cx + dx) + '_' + (cy + dy);
                if (this.cells.has(key)) {
                    const indices = this.cells.get(key);
                    for (const idx of indices) {
                        if (idx !== particleIndex) {
                            neighbors.push(idx);
                        }
                    }
                }
            }
        }
        return neighbors;
    }

    computeDensity() {
        for (let i = 0; i < this.particles.length; i++) {
            const pi = this.particles[i];
            pi.density = 0;
            const neighbors = this.getNeighbors(i);

            for (const j of neighbors) {
                const pj = this.particles[j];
                const dx = pj.x - pi.x;
                const dy = pj.y - pi.y;
                const r = Math.sqrt(dx * dx + dy * dy);

                if (r < this.kernel.h) {
                    pi.density += pj.mass * this.kernel.evaluate(r);
                }
            }

            pi.density += pi.mass * this.kernel.evaluate(0);
            pi.density = Math.max(pi.density, this.restDensity * 0.1);
        }
    }

    computePressure() {
        for (const p of this.particles) {
            p.pressure = this.gasConstant * (p.density - this.restDensity);
            p.pressure = Math.max(p.pressure, -1000);
        }
    }

    computeAccelerations() {
        const invRho0 = 1 / (this.restDensity * this.restDensity);

        for (let i = 0; i < this.particles.length; i++) {
            const pi = this.particles[i];
            pi.ax = 0;
            pi.ay = 0;

            const neighbors = this.getNeighbors(i);

            for (const j of neighbors) {
                const pj = this.particles[j];
                const dx = pj.x - pi.x;
                const dy = pj.y - pi.y;
                const r = Math.sqrt(dx * dx + dy * dy);

                if (r < this.kernel.h && r > 1e-6) {
                    const pressureTerm = pj.mass * (pi.pressure + pj.pressure) /
                                       (2 * pj.density + 1e-6) * invRho0;
                    const grad = this.kernel.gradient(r, dx, dy);
                    pi.ax -= pressureTerm * grad.x;
                    pi.ay -= pressureTerm * grad.y;

                    const viscLap = this.kernel.laplacian(r);
                    const viscTerm = this.viscosity * pj.mass / (pj.density + 1e-6) * viscLap;
                    pi.ax += viscTerm * (pj.vx - pi.vx);
                    pi.ay += viscTerm * (pj.vy - pi.vy);
                }
            }

            pi.ay += this.gravity;

            this.applyCouetteDrag(pi);

            this.applyBoundaryPenalty(pi);
        }
    }

    applyCouetteDrag(particle) {
        const dx = particle.x - this.centerX - this.eccentricityX;
        const dy = particle.y - this.centerY;
        const r = Math.sqrt(dx * dx + dy * dy);

        if (r < 1e-6) return;

        const wallRadius = this.boundaryInner;
        const wallSpeed = this.omega * wallRadius;

        const speedRatio = (r - this.boundaryInner) / Math.max(this.boundaryOuter - this.boundaryInner, 1);
        const targetSpeed = wallSpeed * (1 - speedRatio * 0.7);

        const tangX = -dy / r;
        const tangY = dx / r;

        const particleTangSpeed = particle.vx * tangX + particle.vy * tangY;
        const speedDiff = targetSpeed - particleTangSpeed;

        const dragCoeff = 2.0;
        particle.ax += dragCoeff * speedDiff * tangX;
        particle.ay += dragCoeff * speedDiff * tangY;
    }

    applyBoundaryPenalty(particle) {
        const dx = particle.x - this.centerX - this.eccentricityX;
        const dy = particle.y - this.centerY;
        const r = Math.sqrt(dx * dx + dy * dy);

        if (r < 1e-6) return;

        const normX = dx / r;
        const normY = dy / r;

        if (r < this.boundaryInner) {
            const delta = this.boundaryInner - r;
            const forceMag = this.boundaryForce * delta * delta;
            particle.ax += forceMag * normX;
            particle.ay += forceMag * normY;
        }

        if (r > this.boundaryOuter) {
            const delta = r - this.boundaryOuter;
            const forceMag = this.boundaryForce * delta * delta;
            particle.ax -= forceMag * normX;
            particle.ay -= forceMag * normY;
        }
    }

    enforceBoundaryReflection(particle) {
        const dx = particle.x - this.centerX - this.eccentricityX;
        const dy = particle.y - this.centerY;
        const r = Math.sqrt(dx * dx + dy * dy);

        if (r < 1e-6) return;

        const normX = dx / r;
        const normY = dy / r;
        const tangX = -normY;
        const tangY = normX;

        let pushed = false;

        if (r < this.boundaryInner + 1) {
            const pIn = particle.vx * normX + particle.vy * normY;
            const pTan = particle.vx * tangX + particle.vy * tangY;

            if (pIn < 0) {
                particle.vx = this.boundaryRestitution * (-pIn) * normX + pTan * tangX;
                particle.vy = this.boundaryRestitution * (-pIn) * normY + pTan * tangY;

                particle.x = this.centerX + this.eccentricityX + normX * (this.boundaryInner + 1);
                particle.y = this.centerY + normY * (this.boundaryInner + 1);
                pushed = true;
            }
        }

        if (r > this.boundaryOuter - 1) {
            const pOut = particle.vx * normX + particle.vy * normY;
            const pTan = particle.vx * tangX + particle.vy * tangY;

            if (pOut > 0) {
                particle.vx = this.boundaryRestitution * (-pOut) * normX + pTan * tangX;
                particle.vy = this.boundaryRestitution * (-pOut) * normY + pTan * tangY;

                particle.x = this.centerX + this.eccentricityX + normX * (this.boundaryOuter - 1);
                particle.y = this.centerY + normY * (this.boundaryOuter - 1);
                pushed = true;
            }
        }

        return pushed;
    }

    updateParticlePhase(particle, time) {
        particle.phase += this.omega * this.dt;

        const dx = particle.x - this.centerX - this.eccentricityX;
        const dy = particle.y - this.centerY;
        const r = Math.sqrt(dx * dx + dy * dy);

        let pressure = 0;
        if (r > 0) {
            const angle = Math.atan2(dy, dx);
            const filmThickness = 1 + this.eccentricity * Math.cos(angle);
            pressure = Math.exp(-Math.pow((angle - 0.5) / 0.8, 2)) * filmThickness;
        }

        const cavThreshold = 0.05;
        particle.isInCavitation = pressure < cavThreshold;

        if (particle.isInCavitation) {
            particle.color = { r: 200, g: 220, b: 255 };
        } else {
            const pressureColor = Math.min(255, 100 + pressure * 150);
            particle.color = {
                r: 50 + pressure * 100,
                g: 150 + pressure * 50,
                b: 255
            };
        }
    }

    step(time) {
        this.eccentricityX = this.eccentricity * (this.boundaryOuter - this.boundaryInner) * 0.5;

        this.buildNeighborList();
        this.computeDensity();
        this.computePressure();
        this.computeAccelerations();

        for (const p of this.particles) {
            p.vx += p.ax * this.dt;
            p.vy += p.ay * this.dt;
            p.vx *= this.damping;
            p.vy *= this.damping;
            p.x += p.vx * this.dt;
            p.y += p.vy * this.dt;

            this.enforceBoundaryReflection(p);
            this.updateParticlePhase(p, time);
        }
    }

    getPressureAtPosition(x, y) {
        let pressure = 0;
        let weight = 0;

        for (const p of this.particles) {
            const dx = p.x - x;
            const dy = p.y - y;
            const r = Math.sqrt(dx * dx + dy * dy);

            if (r < this.kernel.h) {
                const w = this.kernel.evaluate(r);
                pressure += p.pressure * w;
                weight += w;
            }
        }

        return weight > 0 ? pressure / weight : 0;
    }
}

class WaterFilmParticles {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');

        this.time = 0;
        this.particleCount = 500;
        this.speedFactor = 0.5;
        this.rpm = 35;
        this.eccentricity = 0.3;

        this.sph = new SPHSolver({
            kernelRadius: 12,
            restDensity: 1000,
            gasConstant: 300,
            viscosity: 2.0,
            boundaryInner: 100,
            boundaryOuter: 120,
            omega: 0.5,
            boundaryRestitution: 0.2,
            boundaryForce: 8000,
        });

        this.animationId = null;
        this.showPressureField = false;
        this.showVectors = false;

        this.init();
    }

    init() {
        this.resize();
        window.addEventListener('resize', () => this.resize());
        this.initParticles();
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

        const scale = Math.min(this.width, this.height) / 320;
        this.sph.boundaryInner = 100 * scale;
        this.sph.boundaryOuter = 120 * scale;
        this.sph.centerX = this.centerX;
        this.sph.centerY = this.centerY;
        this.sph.kernel.h = 12 * scale;
        this.sph.cellSize = this.sph.kernel.h;

        this.initParticles();
    }

    initParticles() {
        this.sph.clearParticles();
        this.sph.setParticleCount(this.particleCount);
    }

    setParticleCount(count) {
        this.particleCount = count;
        this.sph.setParticleCount(count);
    }

    setSpeed(speed) {
        this.speedFactor = speed / 50;
    }

    setRpm(rpm) {
        this.rpm = rpm;
        this.sph.omega = rpm * 2 * Math.PI / 60 * this.speedFactor * 0.3;
    }

    setEccentricity(ecc) {
        this.eccentricity = ecc;
        this.sph.eccentricity = ecc;
    }

    drawBackground() {
        this.ctx.clearRect(0, 0, this.width, this.height);

        const gradient = this.ctx.createRadialGradient(
            this.centerX, this.centerY, this.sph.boundaryInner * 0.5,
            this.centerX, this.centerY, this.sph.boundaryOuter * 1.5
        );
        gradient.addColorStop(0, 'rgba(30, 80, 130, 0.3)');
        gradient.addColorStop(1, 'rgba(10, 30, 60, 0.1)');
        this.ctx.fillStyle = gradient;
        this.ctx.fillRect(0, 0, this.width, this.height);
    }

    drawBearing() {
        const eccOff = this.sph.eccentricityX;

        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, this.sph.boundaryOuter + 15, 0, Math.PI * 2);
        const outerGrad = this.ctx.createRadialGradient(
            this.centerX, this.centerY, this.sph.boundaryOuter,
            this.centerX, this.centerY, this.sph.boundaryOuter + 15
        );
        outerGrad.addColorStop(0, '#8d6e63');
        outerGrad.addColorStop(1, '#5d4037');
        this.ctx.fillStyle = outerGrad;
        this.ctx.fill();
        this.ctx.strokeStyle = '#4e342e';
        this.ctx.lineWidth = 2;
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, this.sph.boundaryOuter, 0, Math.PI * 2);
        this.ctx.strokeStyle = '#3e2723';
        this.ctx.lineWidth = 1;
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.arc(this.centerX + eccOff, this.centerY, this.sph.boundaryInner - 10, 0, Math.PI * 2);
        const innerGrad = this.ctx.createRadialGradient(
            this.centerX + eccOff, this.centerY, this.sph.boundaryInner - 15,
            this.centerX + eccOff, this.centerY, this.sph.boundaryInner - 10
        );
        innerGrad.addColorStop(0, '#a1887f');
        innerGrad.addColorStop(1, '#8d6e63');
        this.ctx.fillStyle = innerGrad;
        this.ctx.fill();

        this.ctx.beginPath();
        this.ctx.arc(this.centerX + eccOff, this.centerY, this.sph.boundaryInner, 0, Math.PI * 2);
        this.ctx.strokeStyle = '#bcaaa4';
        this.ctx.lineWidth = 2;
        this.ctx.stroke();

        this.ctx.beginPath();
        this.ctx.arc(this.centerX + eccOff, this.centerY, this.sph.boundaryInner - 10, 0, Math.PI * 2);
        this.ctx.strokeStyle = '#8d6e63';
        this.ctx.lineWidth = 1;
        this.ctx.stroke();
    }

    drawWaterFilm() {
        const eccOff = this.sph.eccentricityX;

        this.ctx.save();

        const filmGradient = this.ctx.createLinearGradient(
            this.centerX + eccOff - this.sph.boundaryInner,
            this.centerY,
            this.centerX + this.sph.boundaryOuter,
            this.centerY
        );
        filmGradient.addColorStop(0, 'rgba(129, 212, 250, 0.5)');
        filmGradient.addColorStop(0.5, 'rgba(79, 195, 247, 0.35)');
        filmGradient.addColorStop(1, 'rgba(41, 182, 246, 0.25)');

        this.ctx.beginPath();
        this.ctx.arc(this.centerX, this.centerY, this.sph.boundaryOuter, 0, Math.PI * 2);
        this.ctx.arc(this.centerX + eccOff, this.centerY, this.sph.boundaryInner, 0, Math.PI * 2, true);
        this.ctx.fillStyle = filmGradient;
        this.ctx.fill('evenodd');

        this.ctx.restore();
    }

    drawCavitationRegions() {
        const cavRegions = this.findCavitationRegions();

        for (const region of cavRegions) {
            this.ctx.save();

            const cavGradient = this.ctx.createRadialGradient(
                region.x, region.y, 0,
                region.x, region.y, region.radius
            );
            cavGradient.addColorStop(0, 'rgba(255, 255, 255, 0.3)');
            cavGradient.addColorStop(0.5, 'rgba(255, 255, 255, 0.15)');
            cavGradient.addColorStop(1, 'rgba(255, 255, 255, 0)');

            this.ctx.beginPath();
            this.ctx.arc(region.x, region.y, region.radius, 0, Math.PI * 2);
            this.ctx.fillStyle = cavGradient;
            this.ctx.fill();

            for (let i = 0; i < 3; i++) {
                const angle = Math.random() * Math.PI * 2;
                const r = Math.random() * region.radius * 0.7;
                const bx = region.x + Math.cos(angle) * r;
                const by = region.y + Math.sin(angle) * r;
                const bubbleR = 1 + Math.random() * 3;

                this.ctx.beginPath();
                this.ctx.arc(bx, by, bubbleR, 0, Math.PI * 2);
                this.ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
                this.ctx.fill();
            }

            this.ctx.restore();
        }
    }

    findCavitationRegions() {
        const regions = [];
        const visited = new Set();
        const threshold = 5;

        for (let i = 0; i < this.sph.particles.length; i++) {
            if (visited.has(i) || !this.sph.particles[i].isInCavitation) continue;

            const cluster = [];
            const queue = [i];
            visited.add(i);

            while (queue.length > 0) {
                const idx = queue.shift();
                cluster.push(idx);

                const neighbors = this.sph.getNeighbors(idx);
                for (const n of neighbors) {
                    if (!visited.has(n) && this.sph.particles[n].isInCavitation) {
                        visited.add(n);
                        queue.push(n);
                    }
                }
            }

            if (cluster.length > threshold) {
                let sumX = 0, sumY = 0, maxR = 0;
                for (const idx of cluster) {
                    sumX += this.sph.particles[idx].x;
                    sumY += this.sph.particles[idx].y;
                }
                const cx = sumX / cluster.length;
                const cy = sumY / cluster.length;

                for (const idx of cluster) {
                    const p = this.sph.particles[idx];
                    const dx = p.x - cx;
                    const dy = p.y - cy;
                    maxR = Math.max(maxR, Math.sqrt(dx * dx + dy * dy));
                }

                regions.push({ x: cx, y: cy, radius: maxR + 5, size: cluster.length });
            }
        }

        return regions;
    }

    drawParticles() {
        for (const p of this.sph.particles) {
            const speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
            const size = 1.5 + speed * 0.05;

            const gradient = this.ctx.createRadialGradient(
                p.x, p.y, 0,
                p.x, p.y, size * 2
            );
            gradient.addColorStop(0, `rgba(${p.color.r}, ${p.color.g}, ${p.color.b}, ${p.isInCavitation ? 0.4 : 0.9})`);
            gradient.addColorStop(1, `rgba(${p.color.r}, ${p.color.g}, ${p.color.b}, 0)`);

            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, size * 2, 0, Math.PI * 2);
            this.ctx.fillStyle = gradient;
            this.ctx.fill();

            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, size * 0.6, 0, Math.PI * 2);
            this.ctx.fillStyle = `rgba(255, 255, 255, ${p.isInCavitation ? 0.3 : 0.8})`;
            this.ctx.fill();
        }
    }

    drawVelocityVectors() {
        if (!this.showVectors) return;

        this.ctx.strokeStyle = 'rgba(255, 255, 100, 0.5)';
        this.ctx.lineWidth = 1;

        for (let i = 0; i < this.sph.particles.length; i += 10) {
            const p = this.sph.particles[i];
            const scale = 3;

            this.ctx.beginPath();
            this.ctx.moveTo(p.x, p.y);
            this.ctx.lineTo(p.x + p.vx * scale, p.y + p.vy * scale);
            this.ctx.stroke();

            const angle = Math.atan2(p.vy, p.vx);
            const headLen = 3;
            this.ctx.beginPath();
            this.ctx.moveTo(p.x + p.vx * scale, p.y + p.vy * scale);
            this.ctx.lineTo(
                p.x + p.vx * scale - headLen * Math.cos(angle - Math.PI / 6),
                p.y + p.vy * scale - headLen * Math.sin(angle - Math.PI / 6)
            );
            this.ctx.lineTo(
                p.x + p.vx * scale - headLen * Math.cos(angle + Math.PI / 6),
                p.y + p.vy * scale - headLen * Math.sin(angle + Math.PI / 6)
            );
            this.ctx.closePath();
            this.ctx.fillStyle = 'rgba(255, 255, 100, 0.7)';
            this.ctx.fill();
        }
    }

    drawPressureField() {
        if (!this.showPressureField) return;

        const resolution = 15;
        const imageData = this.ctx.createImageData(this.width, this.height);
        const data = imageData.data;

        for (let y = 0; y < this.height; y += resolution) {
            for (let x = 0; x < this.width; x += resolution) {
                const pressure = this.sph.getPressureAtPosition(x, y);
                const normPressure = Math.max(0, Math.min(1, (pressure + 500) / 1500));

                const r = Math.floor(50 + normPressure * 200);
                const g = Math.floor(100 + normPressure * 100);
                const b = Math.floor(255 - normPressure * 100);

                for (let dy = 0; dy < resolution; dy++) {
                    for (let dx = 0; dx < resolution; dx++) {
                        const px = x + dx;
                        const py = y + dy;
                        if (px < this.width && py < this.height) {
                            const idx = (py * this.width + px) * 4;
                            data[idx] = r;
                            data[idx + 1] = g;
                            data[idx + 2] = b;
                            data[idx + 3] = 50;
                        }
                    }
                }
            }
        }

        this.ctx.putImageData(imageData, 0, 0);
    }

    drawLabels() {
        this.ctx.fillStyle = '#78909c';
        this.ctx.font = '12px sans-serif';
        this.ctx.fillText('SPH水膜流场仿真', 20, this.height - 15);

        const infoY = 50;
        this.ctx.fillStyle = '#90a4ae';
        this.ctx.font = '11px sans-serif';
        this.ctx.fillText(`粒子数: ${this.sph.particles.length}`, 20, infoY);
        this.ctx.fillText(`转速: ${this.rpm} RPM`, 20, infoY + 18);
        this.ctx.fillText(`偏心率: ${this.eccentricity.toFixed(2)}`, 20, infoY + 36);
        this.ctx.fillText(`方法: SPH (Wendland核)`, 20, infoY + 54);

        const cavCount = this.sph.particles.filter(p => p.isInCavitation).length;
        const cavPercent = (cavCount / this.sph.particles.length * 100).toFixed(1);
        this.ctx.fillText(`空化粒子: ${cavCount} (${cavPercent}%)`, 20, infoY + 72);

        const legendY = this.height - 80;
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
        this.ctx.fillRect(this.width - 160, legendY - 10, 150, 75);

        this.ctx.fillStyle = '#4fc3f7';
        this.ctx.fillRect(this.width - 150, legendY, 20, 12);
        this.ctx.fillStyle = '#b0bec5';
        this.ctx.fillText('水相', this.width - 120, legendY + 10);

        this.ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
        this.ctx.fillRect(this.width - 150, legendY + 20, 20, 12);
        this.ctx.fillStyle = '#b0bec5';
        this.ctx.fillText('汽相(空化)', this.width - 120, legendY + 30);

        this.ctx.fillStyle = '#8d6e63';
        this.ctx.fillRect(this.width - 150, legendY + 40, 20, 12);
        this.ctx.fillStyle = '#b0bec5';
        this.ctx.fillText('轴承壁面', this.width - 120, legendY + 50);
    }

    animate() {
        this.animationId = requestAnimationFrame(() => this.animate());
        this.time++;

        this.sph.omega = this.rpm * 2 * Math.PI / 60 * this.speedFactor * 0.3;
        this.sph.step(this.time);

        this.drawBackground();
        this.drawPressureField();
        this.drawWaterFilm();
        this.drawCavitationRegions();
        this.drawBearing();
        this.drawParticles();
        this.drawVelocityVectors();
        this.drawLabels();
    }

    destroy() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
        }
    }
}
