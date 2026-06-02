import * as pc from 'playcanvas';

export class SceneAlignerControls {
  private app: pc.AppBase;
  private camera: pc.Entity;
  private gsEntity: pc.Entity;
  private sceneRotation: pc.Quat;
  private groundPlaneIndicator: any;
  private orbitControls: any;
  private flyControls: any;

  private handles: { xRing: pc.Entity; yRing: pc.Entity; zRing: pc.Entity; viewRing: pc.Entity } | null = null;
  private picker: pc.Picker | null = null;
  private activeAxis: 'x' | 'y' | 'z' | 'view' | null = null;
  private isDragging: boolean = false;
  private sensitivity: number = 30.0;
  private lastMouseX: number = 0;
  private lastMouseY: number = 0;
  private initialViewAxis: pc.Vec3 | null = null;

  // Store original scene transform for undo
  private originalScenePosition: pc.Vec3 | null = null;
  private originalSceneRotation: pc.Quat | null = null;

  public isActive: boolean = false;

  constructor(
    app: pc.AppBase,
    camera: pc.Entity,
    gsEntity: pc.Entity,
    sceneRotation: pc.Quat,
    groundPlaneIndicator: any,
    orbitControls: any,
    flyControls: any
  ) {
    this.app = app;
    this.camera = camera;
    this.gsEntity = gsEntity;
    this.sceneRotation = sceneRotation;
    this.groundPlaneIndicator = groundPlaneIndicator;
    this.orbitControls = orbitControls;
    this.flyControls = flyControls;
  }

  private createHandles() {
    if (this.handles) return;

    const overlayLayer = this.app.scene.layers.getLayerByName('Overlay');
    if (!overlayLayer) return;

    const handleSize = 2.0;

    // Create torus meshes
    const createTorus = () => {
      return pc.createTorus(this.app.graphicsDevice, {
        tubeRadius: 0.05,
        ringRadius: 1.0,
        segments: 32,
        sides: 16
      });
    };

    // X-axis ring (red)
    const xRing = new pc.Entity('xRotationRing');
    const xMaterial = new pc.StandardMaterial();
    xMaterial.diffuse = new pc.Color(1, 0, 0);
    xMaterial.emissive = new pc.Color(1, 0, 0);
    xMaterial.opacity = 0.7;
    xMaterial.blendType = pc.BLEND_NORMAL;
    xMaterial.depthWrite = false;
    xMaterial.useLighting = false;
    xMaterial.update();

    xRing.addComponent('render', {
      type: 'asset',
      meshInstances: [new pc.MeshInstance(createTorus(), xMaterial)],
      castShadows: false,
      receiveShadows: false,
      layers: [overlayLayer.id]
    });
    xRing.setLocalScale(handleSize, handleSize, handleSize);
    xRing.setLocalEulerAngles(0, 0, 90);
    this.app.root.addChild(xRing);

    // Y-axis ring (green)
    const yRing = new pc.Entity('yRotationRing');
    const yMaterial = new pc.StandardMaterial();
    yMaterial.diffuse = new pc.Color(0, 1, 0);
    yMaterial.emissive = new pc.Color(0, 1, 0);
    yMaterial.opacity = 0.7;
    yMaterial.blendType = pc.BLEND_NORMAL;
    yMaterial.depthWrite = false;
    yMaterial.useLighting = false;
    yMaterial.update();

    yRing.addComponent('render', {
      type: 'asset',
      meshInstances: [new pc.MeshInstance(createTorus(), yMaterial)],
      castShadows: false,
      receiveShadows: false,
      layers: [overlayLayer.id]
    });
    yRing.setLocalScale(handleSize, handleSize, handleSize);
    this.app.root.addChild(yRing);

    // Z-axis ring (blue)
    const zRing = new pc.Entity('zRotationRing');
    const zMaterial = new pc.StandardMaterial();
    zMaterial.diffuse = new pc.Color(0, 0, 1);
    zMaterial.emissive = new pc.Color(0, 0, 1);
    zMaterial.opacity = 0.7;
    zMaterial.blendType = pc.BLEND_NORMAL;
    zMaterial.depthWrite = false;
    zMaterial.useLighting = false;
    zMaterial.update();

    zRing.addComponent('render', {
      type: 'asset',
      meshInstances: [new pc.MeshInstance(createTorus(), zMaterial)],
      castShadows: false,
      receiveShadows: false,
      layers: [overlayLayer.id]
    });
    zRing.setLocalScale(handleSize, handleSize, handleSize);
    zRing.setLocalEulerAngles(90, 0, 0);
    this.app.root.addChild(zRing);

    // View-axis ring (yellow) - always faces the camera, larger radius
    const viewRing = new pc.Entity('viewRotationRing');
    const viewMaterial = new pc.StandardMaterial();
    viewMaterial.diffuse = new pc.Color(1, 1, 0);
    viewMaterial.emissive = new pc.Color(1, 1, 0);
    viewMaterial.opacity = 0.7;
    viewMaterial.blendType = pc.BLEND_NORMAL;
    viewMaterial.depthWrite = false;
    viewMaterial.useLighting = false;
    viewMaterial.update();

    viewRing.addComponent('render', {
      type: 'asset',
      meshInstances: [new pc.MeshInstance(createTorus(), viewMaterial)],
      castShadows: false,
      receiveShadows: false,
      layers: [overlayLayer.id]
    });
    viewRing.setLocalScale(handleSize * 1.2, handleSize * 1.2, handleSize * 1.2); // 20% larger
    this.app.root.addChild(viewRing);

    this.handles = { xRing, yRing, zRing, viewRing };

    // Initially hidden
    xRing.enabled = false;
    yRing.enabled = false;
    zRing.enabled = false;
    viewRing.enabled = false;
  }

  private getRotationCenter(): pc.Vec3 {
    // Use orbital pivot point if available, otherwise origin
    if (this.orbitControls && this.orbitControls.pivotPoint) {
      return this.orbitControls.pivotPoint.clone();
    }
    return new pc.Vec3(0, 0, 0);
  }

  private updateHandlesPosition() {
    if (!this.handles) return;

    const centerPos = this.getRotationCenter();

    this.handles.xRing.setPosition(centerPos);
    this.handles.yRing.setPosition(centerPos);
    this.handles.zRing.setPosition(centerPos);
    this.handles.viewRing.setPosition(centerPos);

    // Make viewRing always face the camera (billboard)
    const camPos = this.camera.getPosition();
    this.handles.viewRing.lookAt(camPos);
    this.handles.viewRing.rotateLocal(90, 0, 0); // Rotate 90 degrees to make it perpendicular
  }

  public update() {
    if (!this.handles || !this.isActive) return;

    // Update handles position to follow pivot
    this.updateHandlesPosition();

    // Update scale based on distance from camera for constant screen space size
    const centerPos = this.getRotationCenter();
    const camPos = this.camera.getPosition();
    const distance = centerPos.distance(camPos);

    // Scale factor to maintain constant screen space size
    const screenSpaceScale = distance * 0.15; // Adjust multiplier for desired size

    this.handles.xRing.setLocalScale(screenSpaceScale, screenSpaceScale, screenSpaceScale);
    this.handles.yRing.setLocalScale(screenSpaceScale, screenSpaceScale, screenSpaceScale);
    this.handles.zRing.setLocalScale(screenSpaceScale, screenSpaceScale, screenSpaceScale);
    this.handles.viewRing.setLocalScale(screenSpaceScale * 1.2, screenSpaceScale * 1.2, screenSpaceScale * 1.2);
  }

  public toggle() {
    this.isActive = !this.isActive;

    if (this.isActive) {
      this.enable();
    } else {
      this.disable();
    }
  }

  public enable() {
    this.isActive = true;

    // Store original scene transform for undo
    if (this.gsEntity) {
      this.originalScenePosition = this.gsEntity.getPosition().clone();
      this.originalSceneRotation = this.gsEntity.getRotation().clone();
    }

    // Show ground plane
    if (this.groundPlaneIndicator && !this.groundPlaneIndicator.isVisible()) {
      this.groundPlaneIndicator.toggle();
    }

    // Create and show rotation handles
    this.createHandles();
    if (this.handles) {
      this.updateHandlesPosition();
      this.update(); // Initial scale update for constant screen space size
      this.handles.xRing.enabled = true;
      this.handles.yRing.enabled = true;
      this.handles.zRing.enabled = true;
      this.handles.viewRing.enabled = true;
    }

    // Keep orbital controls enabled - scene rotation works alongside them
    // Only disable fly controls
    if (this.flyControls) this.flyControls.enabled = false;

    // Set up event handlers for scene rotation handles
    // These will only activate when clicking/tapping on the handles themselves
    if (this.app.mouse) {
      this.app.mouse.on(pc.EVENT_MOUSEMOVE, this.onMouseMove);
      this.app.mouse.on(pc.EVENT_MOUSEDOWN, this.onMouseDown);
      this.app.mouse.on(pc.EVENT_MOUSEUP, this.onMouseUp);
    }

    // Also add touch support
    if (this.app.touch) {
      this.app.touch.on(pc.EVENT_TOUCHSTART, this.onTouchStart);
      this.app.touch.on(pc.EVENT_TOUCHMOVE, this.onTouchMove);
      this.app.touch.on(pc.EVENT_TOUCHEND, this.onTouchEnd);
    }
  }

  public disable() {
    this.isActive = false;

    // Hide rotation handles
    if (this.handles) {
      this.handles.xRing.enabled = false;
      this.handles.yRing.enabled = false;
      this.handles.zRing.enabled = false;
      this.handles.viewRing.enabled = false;
    }

    // Remove event handlers
    if (this.app.mouse) {
      this.app.mouse.off(pc.EVENT_MOUSEMOVE, this.onMouseMove);
      this.app.mouse.off(pc.EVENT_MOUSEDOWN, this.onMouseDown);
      this.app.mouse.off(pc.EVENT_MOUSEUP, this.onMouseUp);
    }

    if (this.app.touch) {
      this.app.touch.off(pc.EVENT_TOUCHSTART, this.onTouchStart);
      this.app.touch.off(pc.EVENT_TOUCHMOVE, this.onTouchMove);
      this.app.touch.off(pc.EVENT_TOUCHEND, this.onTouchEnd);
    }

    this.activeAxis = null;
    this.isDragging = false;

    // Ensure orbital controls are re-enabled
    if (this.orbitControls) {
      this.orbitControls.enabled = true;
    }
  }

  private onMouseDown = (event: pc.MouseEvent) => {
    if (event.button === pc.MOUSEBUTTON_LEFT && this.handles) {
      if (!this.picker) {
        this.picker = new pc.Picker(this.app, 256, 256);
      }

      const overlayLayer = this.app.scene.layers.getLayerByName('Overlay');
      if (!overlayLayer) return;

      this.picker.resize(this.app.graphicsDevice.width, this.app.graphicsDevice.height);
      this.picker.prepare(this.camera.camera!, this.app.scene, [overlayLayer]);

      const selection = this.picker.getSelection(event.x, event.y);

      if (selection.length > 0) {
        const picked = selection[0];

        if (picked.node === this.handles.xRing) {
          this.activeAxis = 'x';
          const oldMeshInstance = this.handles.xRing.render!.meshInstances[0];
          const newMat = new pc.StandardMaterial();
          newMat.diffuse.set(1, 1, 1);
          newMat.emissive.set(1, 1, 1);
          newMat.opacity = 1.0;
          newMat.blendType = pc.BLEND_NORMAL;
          newMat.depthWrite = false;
          newMat.depthTest = false;
          newMat.useLighting = false;
          newMat.update();
          this.handles.xRing.render!.meshInstances = [new pc.MeshInstance(oldMeshInstance.mesh, newMat)];
        } else if (picked.node === this.handles.yRing) {
          this.activeAxis = 'y';
          const oldMeshInstance = this.handles.yRing.render!.meshInstances[0];
          const newMat = new pc.StandardMaterial();
          newMat.diffuse.set(1, 1, 1);
          newMat.emissive.set(1, 1, 1);
          newMat.opacity = 1.0;
          newMat.blendType = pc.BLEND_NORMAL;
          newMat.depthWrite = false;
          newMat.depthTest = false;
          newMat.useLighting = false;
          newMat.update();
          this.handles.yRing.render!.meshInstances = [new pc.MeshInstance(oldMeshInstance.mesh, newMat)];
        } else if (picked.node === this.handles.zRing) {
          this.activeAxis = 'z';
          const oldMeshInstance = this.handles.zRing.render!.meshInstances[0];
          const newMat = new pc.StandardMaterial();
          newMat.diffuse.set(1, 1, 1);
          newMat.emissive.set(1, 1, 1);
          newMat.opacity = 1.0;
          newMat.blendType = pc.BLEND_NORMAL;
          newMat.depthWrite = false;
          newMat.depthTest = false;
          newMat.useLighting = false;
          newMat.update();
          this.handles.zRing.render!.meshInstances = [new pc.MeshInstance(oldMeshInstance.mesh, newMat)];
        } else if (picked.node === this.handles.viewRing) {
          this.activeAxis = 'view';
          const oldMeshInstance = this.handles.viewRing.render!.meshInstances[0];
          const newMat = new pc.StandardMaterial();
          newMat.diffuse.set(1, 1, 1);
          newMat.emissive.set(1, 1, 1);
          newMat.opacity = 1.0;
          newMat.blendType = pc.BLEND_NORMAL;
          newMat.depthWrite = false;
          newMat.depthTest = false;
          newMat.useLighting = false;
          newMat.update();
          this.handles.viewRing.render!.meshInstances = [new pc.MeshInstance(oldMeshInstance.mesh, newMat)];
        }

        if (this.activeAxis) {
          this.isDragging = true;
          this.lastMouseX = event.x;
          this.lastMouseY = event.y;

          // Store initial view axis if rotating around view
          if (this.activeAxis === 'view') {
            this.initialViewAxis = this.camera.forward.clone();
          }

          // Disable orbital controls while dragging a handle
          if (this.orbitControls) {
            this.orbitControls.enabled = false;
          }
        }
      }
    }
  };

  private onMouseUp = (event: pc.MouseEvent) => {
    if (event.button === pc.MOUSEBUTTON_LEFT) {
      this.isDragging = false;

      // Re-enable orbital controls after dragging
      if (this.orbitControls) {
        this.orbitControls.enabled = true;
      }

      // Reset all ring materials
      if (this.handles) {
        // Red ring
        const xOldMeshInstance = this.handles.xRing.render!.meshInstances[0];
        const xMat = new pc.StandardMaterial();
        xMat.diffuse.set(1, 0, 0);
        xMat.emissive.set(1, 0, 0);
        xMat.opacity = 0.7;
        xMat.blendType = pc.BLEND_NORMAL;
        xMat.depthWrite = false;
        xMat.useLighting = false;
        xMat.update();
        this.handles.xRing.render!.meshInstances = [new pc.MeshInstance(xOldMeshInstance.mesh, xMat)];

        // Green ring
        const yOldMeshInstance = this.handles.yRing.render!.meshInstances[0];
        const yMat = new pc.StandardMaterial();
        yMat.diffuse.set(0, 1, 0);
        yMat.emissive.set(0, 1, 0);
        yMat.opacity = 0.7;
        yMat.blendType = pc.BLEND_NORMAL;
        yMat.depthWrite = false;
        yMat.useLighting = false;
        yMat.update();
        this.handles.yRing.render!.meshInstances = [new pc.MeshInstance(yOldMeshInstance.mesh, yMat)];

        // Blue ring
        const zOldMeshInstance = this.handles.zRing.render!.meshInstances[0];
        const zMat = new pc.StandardMaterial();
        zMat.diffuse.set(0, 0, 1);
        zMat.emissive.set(0, 0, 1);
        zMat.opacity = 0.7;
        zMat.blendType = pc.BLEND_NORMAL;
        zMat.depthWrite = false;
        zMat.useLighting = false;
        zMat.update();
        this.handles.zRing.render!.meshInstances = [new pc.MeshInstance(zOldMeshInstance.mesh, zMat)];

        // Yellow view ring
        const viewOldMeshInstance = this.handles.viewRing.render!.meshInstances[0];
        const viewMat = new pc.StandardMaterial();
        viewMat.diffuse.set(1, 1, 0);
        viewMat.emissive.set(1, 1, 0);
        viewMat.opacity = 0.7;
        viewMat.blendType = pc.BLEND_NORMAL;
        viewMat.depthWrite = false;
        viewMat.useLighting = false;
        viewMat.update();
        this.handles.viewRing.render!.meshInstances = [new pc.MeshInstance(viewOldMeshInstance.mesh, viewMat)];
      }

      this.activeAxis = null;
      this.initialViewAxis = null;
    }
  };

  private onMouseMove = (event: pc.MouseEvent) => {
    if (!this.isDragging || !this.activeAxis) return;

    // Get the pivot point
    const pivot = this.getRotationCenter();

    // Determine rotation axis
    let rotationAxis: pc.Vec3;

    if (this.activeAxis === 'x') {
      rotationAxis = pc.Vec3.RIGHT;
    } else if (this.activeAxis === 'y') {
      rotationAxis = pc.Vec3.UP;
    } else if (this.activeAxis === 'z') {
      rotationAxis = pc.Vec3.FORWARD;
    } else { // view - rotate around initial camera forward (stored when drag started)
      rotationAxis = this.initialViewAxis || this.camera.forward.clone();
    }

    // Get camera rays for old and new mouse positions
    const cam = this.camera.camera!;
    const oldRay = cam.screenToWorld(this.lastMouseX, this.lastMouseY, 1);
    const newRay = cam.screenToWorld(event.x, event.y, 1);
    const camPos = this.camera.getPosition();

    // Calculate ray directions
    const oldDir = new pc.Vec3();
    oldDir.sub2(oldRay, camPos).normalize();
    const newDir = new pc.Vec3();
    newDir.sub2(newRay, camPos).normalize();

    // Project rays onto the plane perpendicular to rotation axis, passing through pivot
    // Plane equation: dot(P - pivot, rotationAxis) = 0
    // Ray: P = camPos + t * dir
    // Solve: dot(camPos + t * dir - pivot, rotationAxis) = 0

    const pivotToCam = new pc.Vec3();
    pivotToCam.sub2(camPos, pivot);

    const oldT = -pivotToCam.dot(rotationAxis) / oldDir.dot(rotationAxis);
    const newT = -pivotToCam.dot(rotationAxis) / newDir.dot(rotationAxis);

    // Calculate intersection points on the plane
    const oldPoint = new pc.Vec3();
    oldPoint.copy(camPos).add(oldDir.mulScalar(oldT));
    const newPoint = new pc.Vec3();
    newPoint.copy(camPos).add(newDir.mulScalar(newT));

    // Get vectors from pivot to these points
    const oldVec = new pc.Vec3();
    oldVec.sub2(oldPoint, pivot).normalize();
    const newVec = new pc.Vec3();
    newVec.sub2(newPoint, pivot).normalize();

    // Calculate angle between vectors
    const cosAngle = oldVec.dot(newVec);
    const angle = Math.acos(pc.math.clamp(cosAngle, -1, 1));

    // Determine sign using cross product
    const cross = new pc.Vec3();
    cross.cross(oldVec, newVec);
    const sign = cross.dot(rotationAxis) > 0 ? 1 : -1;

    const degrees = angle * pc.math.RAD_TO_DEG * sign * this.sensitivity;

    if (Math.abs(degrees) > 0.001) {
      const rotQuat = new pc.Quat();
      rotQuat.setFromAxisAngle(rotationAxis, degrees * pc.math.DEG_TO_RAD);

      // Store the pivot in world space - it should never move
      const worldPivot = pivot.clone();

      if (this.gsEntity) {
        // Get current scene transform
        const scenePos = this.gsEntity.getPosition();
        const sceneRot = this.gsEntity.getRotation();

        // Rotate the scene's position around the world pivot point
        const pivotToScene = new pc.Vec3();
        pivotToScene.sub2(scenePos, worldPivot);
        rotQuat.transformVector(pivotToScene, pivotToScene);
        scenePos.add2(worldPivot, pivotToScene);
        this.gsEntity.setPosition(scenePos);

        // Apply rotation to scene orientation
        const newRot = new pc.Quat();
        newRot.mul2(rotQuat, sceneRot);
        this.gsEntity.setRotation(newRot);

        // Update accumulated scene rotation for tracking
        this.sceneRotation.copy(newRot);
      }

      // CAMERA STAYS FIXED - we're just reorienting the scene/world
      // Don't rotate camera position or orientation
    }

    // Update last mouse position
    this.lastMouseX = event.x;
    this.lastMouseY = event.y;

    // No need to update camera orientation - camera is fixed
    // But we should recalculate orbital controls since the scene moved
    if (this.orbitControls) {
      this.orbitControls.recalculateFromCameraAndPivot();
    }
  };

  // Touch event handlers - convert to mouse events for unified handling
  private onTouchStart = (event: pc.TouchEvent) => {
    if (event.touches.length === 1) {
      // Convert touch to mock mouse event
      const mockEvent = {
        x: event.touches[0].x,
        y: event.touches[0].y,
        button: pc.MOUSEBUTTON_LEFT,
        dx: 0,
        dy: 0,
        event: event.event as any,
        element: event.event?.target as HTMLElement,
      } as unknown as pc.MouseEvent;

      this.onMouseDown(mockEvent);
    }
  };

  private onTouchMove = (event: pc.TouchEvent) => {
    if (event.touches.length === 1 && this.isDragging) {
      // Convert touch to mock mouse event
      const mockEvent = {
        x: event.touches[0].x,
        y: event.touches[0].y,
        button: pc.MOUSEBUTTON_LEFT,
        dx: event.touches[0].x - this.lastMouseX,
        dy: event.touches[0].y - this.lastMouseY,
        event: event.event as any,
        element: event.event?.target as HTMLElement,
      } as unknown as pc.MouseEvent;

      this.onMouseMove(mockEvent);
    }
  };

  private onTouchEnd = (event: pc.TouchEvent) => {
    if (this.isDragging) {
      // Convert touch to mock mouse event
      const mockEvent = {
        x: this.lastMouseX,
        y: this.lastMouseY,
        button: pc.MOUSEBUTTON_LEFT,
        dx: 0,
        dy: 0,
        event: event.event as any,
        element: event.event?.target as HTMLElement,
      } as unknown as pc.MouseEvent;

      this.onMouseUp(mockEvent);
    }
  };

  public undo() {
    if (this.gsEntity && this.originalScenePosition && this.originalSceneRotation) {
      this.gsEntity.setPosition(this.originalScenePosition);
      this.gsEntity.setRotation(this.originalSceneRotation);
      this.sceneRotation.copy(this.originalSceneRotation);

      // Recalculate orbital controls
      if (this.orbitControls) {
        this.orbitControls.recalculateFromCameraAndPivot();
      }
    }
  }

  public apply() {
    // Apply means we keep the current transform and update the "original" baseline
    // This allows the user to apply and then make more adjustments
    if (this.gsEntity) {
      this.originalScenePosition = this.gsEntity.getPosition().clone();
      this.originalSceneRotation = this.gsEntity.getRotation().clone();
    }
  }

  public destroy() {
    this.disable();
    if (this.handles) {
      this.handles.xRing.destroy();
      this.handles.yRing.destroy();
      this.handles.zRing.destroy();
      this.handles = null;
    }
    if (this.picker) {
      this.picker = null;
    }
  }
}

