class Bearing3D {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
        this.bearingGroup = null;
        this.outerRing = null;
        this.innerRing = null;
        this.waterFilm = null;
        this.particles = [];
        this.particleSystem = null;
        this.animationId = null;
        this.rotationSpeed = 0.005;
        this.eccentricity = 0.3;
        this.showParticles = true;

        this.bearingRadius = 5;
        this.bearingLength = 8;
        this.clearance = 0.2;

        this.init();
    }

    init() {
        const width = this.container.clientWidth;
        const height = this.container.clientHeight;

        this.scene = new THREE.Scene();
        this.scene.background = null;
        this.scene.fog = new THREE.Fog(0x0a1929, 20, 50);

        this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
        this.camera.position.set(12, 8, 12);
        this.camera.lookAt(0, 0, 0);

        this.renderer = new THREE.WebGLRenderer({
            antialias: true,
            alpha: true,
        });
        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(window.devicePixelRatio);
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        this.container.appendChild(this.renderer.domElement);

        this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.05;
        this.controls.minDistance = 5;
        this.controls.maxDistance = 40;

        this.addLights();
        this.createBearing();
        this.createParticles();
        this.addWaterEffect();

        window.addEventListener('resize', () => this.onResize());

        this.animate();
    }

    addLights() {
        const ambientLight = new THREE.AmbientLight(0x404060, 0.5);
        this.scene.add(ambientLight);

        const mainLight = new THREE.DirectionalLight(0xffffff, 0.8);
        mainLight.position.set(10, 15, 10);
        mainLight.castShadow = true;
        mainLight.shadow.mapSize.width = 1024;
        mainLight.shadow.mapSize.height = 1024;
        this.scene.add(mainLight);

        const blueLight = new THREE.PointLight(0x4fc3f7, 0.6, 30);
        blueLight.position.set(-8, 5, 5);
        this.scene.add(blueLight);

        const cyanLight = new THREE.PointLight(0x00bcd4, 0.4, 25);
        cyanLight.position.set(8, -3, -8);
        this.scene.add(cyanLight);
    }

    createBearing() {
        this.bearingGroup = new THREE.Group();
        this.scene.add(this.bearingGroup);

        const outerRadius = this.bearingRadius + this.clearance + 0.8;
        const outerThickness = 0.8;
        const length = this.bearingLength;

        const outerGeo = new THREE.CylinderGeometry(
            outerRadius,
            outerRadius,
            length,
            64,
            1,
            false
        );
        const outerMat = new THREE.MeshStandardMaterial({
            color: 0x8d6e63,
            metalness: 0.6,
            roughness: 0.4,
        });
        this.outerRing = new THREE.Mesh(outerGeo, outerMat);
        this.outerRing.rotation.x = Math.PI / 2;
        this.outerRing.castShadow = true;
        this.outerRing.receiveShadow = true;
        this.bearingGroup.add(this.outerRing);

        const outerInnerGeo = new THREE.CylinderGeometry(
            this.bearingRadius + this.clearance,
            this.bearingRadius + this.clearance,
            length + 0.1,
            64,
            1,
            false
        );
        const outerInnerMat = new THREE.MeshStandardMaterial({
            color: 0x6d4c41,
            metalness: 0.5,
            roughness: 0.5,
            side: THREE.BackSide,
        });
        const outerInner = new THREE.Mesh(outerInnerGeo, outerInnerMat);
        outerInner.rotation.x = Math.PI / 2;
        this.bearingGroup.add(outerInner);

        const innerRadius = this.bearingRadius - 0.6;
        const innerGeo = new THREE.CylinderGeometry(
            innerRadius,
            innerRadius,
            length + 0.5,
            64,
            1,
            false
        );
        const innerMat = new THREE.MeshStandardMaterial({
            color: 0xa1887f,
            metalness: 0.7,
            roughness: 0.3,
        });
        this.innerRing = new THREE.Mesh(innerGeo, innerMat);
        this.innerRing.rotation.x = Math.PI / 2;
        this.innerRing.castShadow = true;
        this.innerRing.receiveShadow = true;
        this.bearingGroup.add(this.innerRing);

        this.createWaterFilm();

        const ringGeo1 = new THREE.TorusGeometry(this.bearingRadius - 0.3, 0.15, 16, 64);
        const ringMat = new THREE.MeshStandardMaterial({
            color: 0x5d4037,
            metalness: 0.8,
            roughness: 0.2,
        });

        const ring1 = new THREE.Mesh(ringGeo1, ringMat);
        ring1.position.z = -length / 2 + 1;
        ring1.rotation.x = Math.PI / 2;
        this.innerRing.add(ring1);

        const ring2 = new THREE.Mesh(ringGeo1, ringMat);
        ring2.position.z = length / 2 - 1;
        ring2.rotation.x = Math.PI / 2;
        this.innerRing.add(ring2);

        this.addGrooves();
    }

    createWaterFilm() {
        const filmRadius = this.bearingRadius + this.clearance * 0.5;
        const length = this.bearingLength - 0.5;

        const filmGeo = new THREE.CylinderGeometry(
            filmRadius,
            filmRadius,
            length,
            64,
            32,
            false
        );

        const filmMat = new THREE.MeshPhysicalMaterial({
            color: 0x4fc3f7,
            transparent: true,
            opacity: 0.35,
            roughness: 0.1,
            metalness: 0.1,
            transmission: 0.6,
            thickness: 0.5,
            side: THREE.DoubleSide,
        });

        this.waterFilm = new THREE.Mesh(filmGeo, filmMat);
        this.waterFilm.rotation.x = Math.PI / 2;
        this.bearingGroup.add(this.waterFilm);

        const innerFilmGeo = new THREE.CylinderGeometry(
            this.bearingRadius + 0.01,
            this.bearingRadius + 0.01,
            length,
            64,
            1,
            false
        );
        const innerFilmMat = new THREE.MeshPhysicalMaterial({
            color: 0x81d4fa,
            transparent: true,
            opacity: 0.2,
            side: THREE.BackSide,
        });
        const innerFilm = new THREE.Mesh(innerFilmGeo, innerFilmMat);
        innerFilm.rotation.x = Math.PI / 2;
        this.innerRing.add(innerFilm);
    }

    addGrooves() {
        const grooveCount = 12;
        const length = this.bearingLength - 0.5;
        const radius = this.bearingRadius + this.clearance * 0.3;

        for (let i = 0; i < grooveCount; i++) {
            const angle = (i / grooveCount) * Math.PI * 2;

            const grooveGeo = new THREE.BoxGeometry(0.1, 0.05, length);
            const grooveMat = new THREE.MeshStandardMaterial({
                color: 0x4fc3f7,
                transparent: true,
                opacity: 0.5,
            });

            const groove = new THREE.Mesh(grooveGeo, grooveMat);
            groove.position.x = Math.cos(angle) * radius;
            groove.position.z = Math.sin(angle) * radius;
            groove.rotation.y = -angle;

            this.waterFilm.add(groove);
        }
    }

    createParticles() {
        const particleCount = 500;
        const positions = new Float32Array(particleCount * 3);
        const velocities = new Float32Array(particleCount * 3);
        const colors = new Float32Array(particleCount * 3);

        for (let i = 0; i < particleCount; i++) {
            const angle = Math.random() * Math.PI * 2;
            const radius = this.bearingRadius + this.clearance * 0.2 + Math.random() * this.clearance * 0.6;
            const z = (Math.random() - 0.5) * (this.bearingLength - 1);

            positions[i * 3] = Math.cos(angle) * radius;
            positions[i * 3 + 1] = z;
            positions[i * 3 + 2] = Math.sin(angle) * radius;

            velocities[i * 3] = 0;
            velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.02;
            velocities[i * 3 + 2] = 0;

            const colorT = Math.random();
            colors[i * 3] = 0.3 + colorT * 0.3;
            colors[i * 3 + 1] = 0.7 + colorT * 0.2;
            colors[i * 3 + 2] = 1.0;
        }

        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

        const material = new THREE.PointsMaterial({
            size: 0.08,
            vertexColors: true,
            transparent: true,
            opacity: 0.8,
            blending: THREE.AdditiveBlending,
            sizeAttenuation: true,
        });

        this.particleSystem = new THREE.Points(geometry, material);
        this.particleSystem.rotation.x = Math.PI / 2;
        this.particleVelocityData = velocities;
        this.bearingGroup.add(this.particleSystem);
    }

    addWaterEffect() {
        const waveGeo = new THREE.RingGeometry(
            this.bearingRadius + 0.5,
            this.bearingRadius + this.clearance + 0.3,
            64
        );
        const waveMat = new THREE.MeshBasicMaterial({
            color: 0x4fc3f7,
            transparent: true,
            opacity: 0.15,
            side: THREE.DoubleSide,
        });

        const wave1 = new THREE.Mesh(waveGeo, waveMat);
        wave1.rotation.x = Math.PI / 2;
        wave1.position.y = this.bearingLength / 2 + 0.1;
        this.bearingGroup.add(wave1);

        const wave2 = new THREE.Mesh(waveGeo, waveMat);
        wave2.rotation.x = Math.PI / 2;
        wave2.position.y = -this.bearingLength / 2 - 0.1;
        this.bearingGroup.add(wave2);
    }

    setEccentricity(value) {
        this.eccentricity = Math.max(0, Math.min(0.95, value));
        const offset = this.eccentricity * this.clearance;
        if (this.innerRing) {
            this.innerRing.position.x = offset;
        }
        if (this.waterFilm) {
            this.waterFilm.position.x = offset * 0.5;
        }
    }

    setRotationSpeed(speed) {
        this.rotationSpeed = speed / 1000;
    }

    setShowParticles(show) {
        this.showParticles = show;
        if (this.particleSystem) {
            this.particleSystem.visible = show;
        }
    }

    setWireframe(wireframe) {
        this.bearingGroup.traverse((child) => {
            if (child.isMesh && child.material) {
                if (Array.isArray(child.material)) {
                    child.material.forEach(m => m.wireframe = wireframe);
                } else {
                    child.material.wireframe = wireframe;
                }
            }
        });
    }

    setParticleCount(count) {
        if (!this.particleSystem) return;

        const positions = new Float32Array(count * 3);
        const velocities = new Float32Array(count * 3);
        const colors = new Float32Array(count * 3);

        for (let i = 0; i < count; i++) {
            const angle = Math.random() * Math.PI * 2;
            const radius = this.bearingRadius + this.clearance * 0.2 + Math.random() * this.clearance * 0.6;
            const z = (Math.random() - 0.5) * (this.bearingLength - 1);

            positions[i * 3] = Math.cos(angle) * radius;
            positions[i * 3 + 1] = z;
            positions[i * 3 + 2] = Math.sin(angle) * radius;

            velocities[i * 3] = 0;
            velocities[i * 3 + 1] = (Math.random() - 0.5) * 0.02;
            velocities[i * 3 + 2] = 0;

            const colorT = Math.random();
            colors[i * 3] = 0.3 + colorT * 0.3;
            colors[i * 3 + 1] = 0.7 + colorT * 0.2;
            colors[i * 3 + 2] = 1.0;
        }

        this.particleSystem.geometry.dispose();
        this.particleSystem.geometry = new THREE.BufferGeometry();
        this.particleSystem.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        this.particleSystem.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        this.particleVelocityData = velocities;
    }

    updateParticles(deltaTime) {
        if (!this.particleSystem || !this.showParticles) return;

        const positions = this.particleSystem.geometry.attributes.position.array;
        const velocities = this.particleVelocityData;
        const count = positions.length / 3;

        const speed = this.rotationSpeed * 50;

        for (let i = 0; i < count; i++) {
            const x = positions[i * 3];
            const y = positions[i * 3 + 1];
            const z = positions[i * 3 + 2];

            const angle = Math.atan2(z, x);
            const radius = Math.sqrt(x * x + z * z);

            const newAngle = angle + speed * 0.02 * (1 + (radius - this.bearingRadius) / this.clearance);

            const wobble = Math.sin(Date.now() * 0.001 + i * 0.5) * 0.002;
            const newRadius = radius + wobble;

            positions[i * 3] = Math.cos(newAngle) * newRadius;
            positions[i * 3 + 2] = Math.sin(newAngle) * newRadius;

            positions[i * 3 + 1] += velocities[i * 3 + 1];

            const halfLen = (this.bearingLength - 1) / 2;
            if (Math.abs(positions[i * 3 + 1]) > halfLen) {
                velocities[i * 3 + 1] *= -0.8;
                positions[i * 3 + 1] = Math.sign(positions[i * 3 + 1]) * halfLen;
            }

            if (newRadius < this.bearingRadius + 0.05 || newRadius > this.bearingRadius + this.clearance - 0.05) {
                const targetRadius = this.bearingRadius + this.clearance * (0.3 + Math.random() * 0.4);
                positions[i * 3] = Math.cos(newAngle) * targetRadius;
                positions[i * 3 + 2] = Math.sin(newAngle) * targetRadius;
            }
        }

        this.particleSystem.geometry.attributes.position.needsUpdate = true;
    }

    animate() {
        this.animationId = requestAnimationFrame(() => this.animate());

        if (this.innerRing) {
            this.innerRing.rotation.y += this.rotationSpeed;
        }

        if (this.waterFilm) {
            this.waterFilm.rotation.y += this.rotationSpeed * 0.3;
        }

        this.updateParticles(0.016);

        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }

    onResize() {
        const width = this.container.clientWidth;
        const height = this.container.clientHeight;

        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
    }

    destroy() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
        }
        if (this.renderer) {
            this.renderer.dispose();
        }
    }
}
