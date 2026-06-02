import * as pc from 'playcanvas';

export class GroundPlaneIndicator {
  private app: pc.AppBase;
  private groundPlane: pc.Entity | null = null;
  private upArrow: pc.Entity | null = null;
  private container: pc.Entity | null = null;
  private visible: boolean = false;

  constructor(app: pc.AppBase) {
    this.app = app;
    this.createGroundPlaneIndicator();
  }

  private createGroundPlaneIndicator() {
    // Get the overlay layer
    const overlayLayer = this.app.scene.layers.getLayerByName('Overlay');
    if (!overlayLayer) {
      console.error('Overlay layer not found for ground plane indicator');
      return;
    }

    // Create container entity - directly under root to avoid any scene transforms
    this.container = new pc.Entity('groundPlaneContainer');
    this.app.root.addChild(this.container);
    this.container.setPosition(0, 0, 0);
    this.container.setRotation(new pc.Quat()); // Ensure identity rotation

    // Create ground plane (semi-transparent square)
    this.groundPlane = new pc.Entity('groundPlane');
    
    const planeMaterial = new pc.StandardMaterial();
    planeMaterial.diffuse = new pc.Color(1, 1, 1);  // White
    planeMaterial.emissive = new pc.Color(1, 1, 1);
    planeMaterial.opacity = 0.8;  // Semi-transparent
    planeMaterial.blendType = pc.BLEND_NORMAL;
    planeMaterial.depthWrite = false;
    planeMaterial.cull = pc.CULLFACE_NONE;  // Render both sides
    planeMaterial.useLighting = false;
    planeMaterial.update();

    this.groundPlane.addComponent('render', {
      type: 'plane',
      material: planeMaterial,
      castShadows: false,
      receiveShadows: false,
      layers: [overlayLayer.id]
    });

    // Scale the ground plane to be smaller
    this.groundPlane.setLocalScale(1, 1, 1);
    
    // Plane is horizontal by default (Y-up), which is what we want for ground
    this.container.addChild(this.groundPlane);

    // Create up arrow (cone pointing up + cylinder as shaft)
    this.upArrow = new pc.Entity('upArrow');
    
    // Arrow cone (tip)
    const arrowTip = new pc.Entity('arrowTip');
    const coneMaterial = new pc.StandardMaterial();
    coneMaterial.diffuse = new pc.Color(0, 1.0, 0);  // Green
    coneMaterial.emissive = new pc.Color(0, 1.0, 0);
    coneMaterial.opacity = 1.0;
    coneMaterial.blendType = pc.BLEND_NORMAL;
    coneMaterial.depthWrite = false;
    coneMaterial.useLighting = false;
    coneMaterial.update();

    arrowTip.addComponent('render', {
      type: 'cone',
      material: coneMaterial,
      castShadows: false,
      receiveShadows: false,
      layers: [overlayLayer.id]
    });
    
    // Position cone at top, scale it (cone points up by default in PlayCanvas)
    arrowTip.setLocalPosition(0, 0.55, 0);  // Just above the shaft
    arrowTip.setLocalScale(0.08, 0.15, 0.08);  // Much thinner cone
    // No rotation needed - cone points up (Y+) by default
    
    this.upArrow.addChild(arrowTip);

    // Arrow shaft (cylinder)
    const arrowShaft = new pc.Entity('arrowShaft');
    const cylinderMaterial = new pc.StandardMaterial();
    cylinderMaterial.diffuse = new pc.Color(0, 1.0, 0);  // Green
    cylinderMaterial.emissive = new pc.Color(0, 1.0, 0);
    cylinderMaterial.opacity = 1.0;
    cylinderMaterial.blendType = pc.BLEND_NORMAL;
    cylinderMaterial.depthWrite = false;
    cylinderMaterial.useLighting = false;
    cylinderMaterial.update();

    arrowShaft.addComponent('render', {
      type: 'cylinder',
      material: cylinderMaterial,
      castShadows: false,
      receiveShadows: false,
      layers: [overlayLayer.id]
    });

    // Position and scale shaft
    arrowShaft.setLocalPosition(0, 0.25, 0);
    arrowShaft.setLocalScale(0.03, 0.5, 0.03);  // Thinner shaft
    
    this.upArrow.addChild(arrowShaft);
    this.container.addChild(this.upArrow);

    // Start hidden
    this.container.enabled = false;
  }

  setVisible(visible: boolean) {
    this.visible = visible;
    if (this.container) {
      this.container.enabled = visible;
    }
  }

  isVisible(): boolean {
    return this.visible;
  }

  toggle() {
    this.setVisible(!this.visible);
  }

  setPosition(position: pc.Vec3) {
    if (this.container) {
      // Follow the pivot point in all three dimensions
      this.container.setPosition(position.x, position.y, position.z);
      // Ensure the ground plane always maintains world orientation
      this.container.setRotation(new pc.Quat());
    }
  }

  destroy() {
    if (this.container) {
      this.container.destroy();
      this.container = null;
    }
    this.groundPlane = null;
    this.upArrow = null;
  }
}

