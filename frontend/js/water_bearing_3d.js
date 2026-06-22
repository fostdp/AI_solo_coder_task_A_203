/**
 * water_bearing_3d.js — 宋代筒车水润滑轴承三维可视化
 * 职责：Three.js 场景、内外圈、水膜、水槽、偏心/转速效果、相机动画
 * 依赖：Three.js r132 + OrbitControls
 */
(function (global) {
  'use strict';

  const WaterBearing3D = function (containerId, options) {
    options = options || {};
    this.container = document.getElementById(containerId);
    if (!this.container) throw new Error('container not found: ' + containerId);

    this.rpm = 0;
    this.eccentricity = 0;
    this.innerAngle = 0;

    // 轴承几何参数（与后端bearing_params.json保持一致）
    this.R = options.outerRadius != null ? options.outerRadius : 5;
    this.clearance = options.clearance != null ? options.clearance : 0.1;
    this.bearingLength = options.length != null ? options.length : 8;
    this.particleCount = options.particleCount != null ? options.particleCount : 500;

    this._initScene();
    this._buildBearing();
    this._startAnimation();
    window.addEventListener('resize', this._onResize.bind(this));
  };

  WaterBearing3D.prototype._initScene = function () {
    const w = this.container.clientWidth || 400;
    const h = this.container.clientHeight || 400;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a1628);
    this.scene.fog = new THREE.Fog(0x0a1628, 20, 80);

    this.camera = new THREE.PerspectiveCamera(50, w / h, 0.1, 1000);
    this.camera.position.set(0, 12, 18);
    this.camera.lookAt(0, 0, 0);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(w, h);
    this.renderer.shadowMap.enabled = true;
    this.container.appendChild(this.renderer.domElement);

    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.minDistance = 5;
    this.controls.maxDistance = 40;
    this.controls.target.set(0, 0, 0);

    const amb = new THREE.AmbientLight(0xffffff, 0.5);
    this.scene.add(amb);
    const dir = new THREE.DirectionalLight(0xffffff, 0.8);
    dir.position.set(10, 15, 10);
    this.scene.add(dir);
    const pt1 = new THREE.PointLight(0x4fc3f7, 0.6, 50);
    pt1.position.set(-10, 5, -8);
    this.scene.add(pt1);
    const pt2 = new THREE.PointLight(0xffb74d, 0.4, 50);
    pt2.position.set(8, -3, 10);
    this.scene.add(pt2);

    this.bearingGroup = new THREE.Group();
    this.scene.add(this.bearingGroup);
  };

  WaterBearing3D.prototype._buildBearing = function () {
    const R = this.R;
    const L = this.bearingLength;
    const c = this.clearance;

    // 外圈（木质）
    const outerMat = new THREE.MeshStandardMaterial({
      color: 0x6d4c2e, roughness: 0.85, metalness: 0.05,
    });
    this.outerRing = new THREE.Mesh(
      new THREE.CylinderGeometry(R + 1.0, R + 1.0, L, 48, 1, true),
      outerMat,
    );
    this.bearingGroup.add(this.outerRing);

    const innerWallMat = new THREE.MeshStandardMaterial({
      color: 0x3e2723, side: THREE.BackSide, roughness: 0.9, metalness: 0,
    });
    this.innerWall = new THREE.Mesh(
      new THREE.CylinderGeometry(R + c, R + c, L, 48, 1, true),
      innerWallMat,
    );
    this.bearingGroup.add(this.innerWall);

    // 内圈（铸铁质感）
    this.innerGroup = new THREE.Group();
    const innerMat = new THREE.MeshStandardMaterial({
      color: 0xbcaaa0, roughness: 0.5, metalness: 0.6,
    });
    this.innerRing = new THREE.Mesh(
      new THREE.CylinderGeometry(R - 0.6, R - 0.6, L + 0.4, 48, 1, true),
      innerMat,
    );
    this.innerGroup.add(this.innerRing);

    const endCapMat = new THREE.MeshStandardMaterial({
      color: 0x8d6e63, roughness: 0.7, metalness: 0.2,
    });
    const topCap = new THREE.Mesh(new THREE.RingGeometry(R - 2.5, R - 0.6, 48), endCapMat);
    topCap.rotation.x = -Math.PI / 2;
    topCap.position.y = L / 2 + 0.05;
    this.innerGroup.add(topCap);
    const bottomCap = topCap.clone();
    bottomCap.position.y = -L / 2 - 0.05;
    bottomCap.rotation.x = Math.PI / 2;
    this.innerGroup.add(bottomCap);
    this.bearingGroup.add(this.innerGroup);

    // 水膜（半透明）
    this.waterFilmGroup = new THREE.Group();
    const waterMat = new THREE.MeshPhysicalMaterial({
      color: 0x00bcd4, transparent: true, opacity: 0.22,
      roughness: 0.05, metalness: 0.0, clearcoat: 1.0, clearcoatRoughness: 0.1,
      side: THREE.DoubleSide,
    });
    this.waterFilm = new THREE.Mesh(
      new THREE.CylinderGeometry(R + c / 2, R + c / 2, L, 64, 1, true),
      waterMat,
    );
    this.waterFilmGroup.add(this.waterFilm);
    this.bearingGroup.add(this.waterFilmGroup);

    // 水槽（12个均匀分布的小水盒）
    for (let i = 0; i < 12; i++) {
      const angle = (i / 12) * Math.PI * 2;
      const channelMat = new THREE.MeshPhysicalMaterial({
        color: 0x00acc1, transparent: true, opacity: 0.45,
        roughness: 0.1, side: THREE.DoubleSide,
      });
      const channel = new THREE.Mesh(new THREE.BoxGeometry(0.3, L * 0.9, 0.35), channelMat);
      channel.position.set(Math.cos(angle) * (R + c / 2), 0, Math.sin(angle) * (R + c / 2));
      channel.rotation.y = angle;
      this.bearingGroup.add(channel);
    }

    // 端面水波
    this.waveTop = new THREE.Mesh(
      new THREE.RingGeometry(R + c / 2 - 0.3, R + c / 2 + 0.3, 64, 8),
      new THREE.MeshBasicMaterial({ color: 0x4dd0e1, transparent: true, opacity: 0.3, side: THREE.DoubleSide }),
    );
    this.waveTop.rotation.x = -Math.PI / 2;
    this.waveTop.position.y = L / 2;
    this.bearingGroup.add(this.waveTop);
    this.waveBottom = this.waveTop.clone();
    this.waveBottom.rotation.x = Math.PI / 2;
    this.waveBottom.position.y = -L / 2;
    this.bearingGroup.add(this.waveBottom);
  };

  WaterBearing3D.prototype.setRPM = function (rpm) {
    this.rpm = rpm || 0;
  };

  WaterBearing3D.prototype.setEccentricity = function (value) {
    this.eccentricity = Math.max(0, Math.min(0.9, value || 0));
    const offset = this.eccentricity * this.clearance;
    this.innerGroup.position.x = offset;
    this.innerGroup.position.z = 0;
    this.waterFilmGroup.position.x = offset;
    this.waterFilmGroup.position.z = 0;
  };

  WaterBearing3D.prototype.setWaterPressure = function (pressureKPa) {
    const p = Math.min(Math.max(0, pressureKPa || 0), 500) / 500;
    const film = this.waterFilm.material;
    film.color.setHSL(0.53 + p * 0.1, 0.8, 0.35 + p * 0.25);
    film.opacity = 0.18 + p * 0.4;
  };

  WaterBearing3D.prototype.setWaterTemperature = function (tempCelsius) {
    const t = Math.min(Math.max(0, tempCelsius || 20), 100) / 100;
    const hue = 0.55 - t * 0.25;
    this.waterFilm.material.color.setHSL(hue, 0.8, 0.4);
  };

  WaterBearing3D.prototype._startAnimation = function () {
    const self = this;
    const animate = function () {
      requestAnimationFrame(animate);
      const delta = 1 / 60;
      const omega = (self.rpm || 0) * 2 * Math.PI / 60;
      self.innerAngle += omega * delta;
      self.innerGroup.rotation.y = self.innerAngle;
      const now = Date.now() / 1000;
      self.waveTop.material.opacity = 0.25 + 0.1 * Math.sin(now * 3);
      self.waveBottom.material.opacity = self.waveTop.material.opacity;
      self.bearingGroup.rotation.y = Math.sin(now * 0.1) * 0.05;
      self.controls.update();
      self.renderer.render(self.scene, self.camera);
    };
    animate();
  };

  WaterBearing3D.prototype._onResize = function () {
    const w = this.container.clientWidth || 400;
    const h = this.container.clientHeight || 400;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  };

  WaterBearing3D.prototype.dispose = function () {
    window.removeEventListener('resize', this._onResize.bind(this));
    if (this.renderer && this.container) {
      this.container.removeChild(this.renderer.domElement);
      this.renderer.dispose();
    }
  };

  global.WaterBearing3D = WaterBearing3D;
})(window);
